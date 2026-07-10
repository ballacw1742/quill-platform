"""Deliverable Pipeline Orchestrator — Phase C.

Turns the single-shot Phase B deliverable producer into a MULTI-STEP CHAIN.
For a piloted deliverable type, runs an ordered sequence of agent steps where
each step reads the prior step's output as its input and appends a NEW VERSION
to the same Deliverable row (building on prior work, never destructive).

Stops before any human-in-the-loop gate (HITL is Phase D). The terminal
automatable state is ``awaiting_human``.

Design notes:
  - Uses the declarative ``steps`` list from each DeliverableRegistryEntry.
  - Step A creates the deliverable v1 via ``create_deliverable_service``.
  - Each subsequent step calls the agent with the prior step's output as
    context, then appends a version via the shared ``_append_version`` helper
    (which replicates the PATCH logic from routes/deliverables.py — same
    version-bump + snapshot contract, but without the HTTP layer).
  - Each step records lineage in ``deliverable.meta`` (step_key + agent_name).
  - Fail-safe: if a step fails, the deliverable is left at its last good
    version (status stays ``in_progress``), and the chain stops cleanly.
  - The request itself must never fail because of chain errors — callers must
    wrap ``run_deliverable_chain`` in their own try/except.
  - Non-piloted intents (no steps) fall back to Phase B single-create.

Public API:
  ``run_deliverable_chain(db, *, user_id, project_id, deliverable_type,
                          seed_message, call_agent)``

  ``call_agent`` is an async callable ``(agent_name: str, message: str) -> str``
  injected by the caller so this module stays testable without HTTP.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deliverable_registry import DELIVERABLE_REGISTRY, DeliverableRegistryEntry
from app.models_deliverables import Deliverable
from app.routes.deliverables import (
    append_deliverable_version_service,
    create_deliverable_service,
)

_log = logging.getLogger("quill.deliverable_pipeline")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _build_step_message(seed_message: str, prompt_suffix: str, prior_output: str | None) -> str:
    """Construct the prompt for a chain step.

    Step A (no prior output): ``{seed_message}\\n\\n{prompt_suffix}``
    Step B+  (with prior):
      ``Prior step output:\\n{prior_output}\\n\\n{seed_message}\\n\\n{prompt_suffix}``
    """
    parts: list[str] = []
    if prior_output:
        parts.append(f"Prior step output:\n{prior_output}")
    parts.append(seed_message)
    if prompt_suffix:
        parts.append(prompt_suffix)
    return "\n\n".join(parts)


async def _append_version(
    db: AsyncSession,
    row: Deliverable,
    *,
    new_content: dict,
    new_status: str,
    new_meta: dict,
) -> None:
    """Append a new version via the SHARED service in routes/deliverables.py
    (append_deliverable_version_service) so there is one version-bump+snapshot
    code path. Never destructive."""
    await append_deliverable_version_service(
        db, row,
        content=new_content,
        status=new_status,
        meta=new_meta,
        change_action="updated",
    )


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


async def run_deliverable_chain(
    db: AsyncSession,
    *,
    user_id: str,
    project_id: str | None,
    deliverable_type: str,
    seed_message: str,
    call_agent: "AsyncCallable[[str, str], str]",  # type: ignore[type-arg]
) -> Deliverable | None:
    """Run the ordered deliverable chain for a piloted deliverable type.

    Parameters
    ----------
    db:
        Async SQLAlchemy session (caller manages lifecycle).
    user_id:
        ID of the user who owns the deliverable.
    project_id:
        Optional project ID to attach the deliverable to.
    deliverable_type:
        Must be a key in DELIVERABLE_REGISTRY with at least one step.
    seed_message:
        The original request message — used as the base prompt for all steps.
    call_agent:
        Async callable ``(agent_name: str, message: str) -> str``.
        Injected by the caller so the orchestrator is testable without HTTP.

    Returns
    -------
    Deliverable | None
        The produced Deliverable row (latest refreshed state), or None if the
        registry entry has no steps (non-piloted — callers use Phase B path).

    Notes
    -----
    - Step A creates v1; each subsequent step appends a version.
    - ``deliverable.meta`` records lineage: ``steps_completed``, ``steps``,
      and ``produced_by`` for each completed step.
    - Fail-safe: a step failure leaves the deliverable at its last good version
      with ``status='in_progress'`` and stops the chain without raising.
    - The caller must wrap this function in try/except if they want to suppress
      ALL errors (including unexpected ones); step-level agent errors are
      already swallowed internally.
    """
    reg: DeliverableRegistryEntry | None = DELIVERABLE_REGISTRY.get(deliverable_type)
    if reg is None or not reg.steps:
        _log.debug(
            "pipeline.no_steps type=%s — skipping chain (Phase B path)",
            deliverable_type,
        )
        return None

    short_message = seed_message[:60].strip()
    title = reg.title_template.format(message=short_message)

    # Accumulated meta across all steps — built up as steps complete.
    meta: dict = {
        "chain_steps": [],      # [{key, agent_name, role, version}] per completed step
        "steps_completed": 0,
    }

    # Track the prior step's output so subsequent steps can build on it.
    prior_output: str | None = None

    # The live Deliverable row (set after step A creates it).
    row: Deliverable | None = None

    for step_index, step in enumerate(reg.steps):
        step_message = _build_step_message(seed_message, step.prompt_suffix, prior_output)

        _log.info(
            "pipeline.step_start type=%s step=%s index=%d/%d agent=%s",
            deliverable_type, step.key, step_index + 1, len(reg.steps), step.agent_name,
        )

        # Call the agent — failures stop the chain but don't raise to the caller.
        try:
            step_output: str = await call_agent(step.agent_name, step_message)
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "pipeline.step_failed type=%s step=%s index=%d agent=%s err=%s — stopping chain",
                deliverable_type, step.key, step_index + 1, step.agent_name, exc,
            )
            # If we already have a row, leave it at its last good version.
            if row is not None:
                _log.info(
                    "pipeline.partial_complete type=%s deliverable_id=%s at_version=%d",
                    deliverable_type, row.id, row.version,
                )
            return row  # None if step A failed (nothing was created)

        step_content: dict = {
            "summary": step_output,
            "seed_message": seed_message,
            "step_key": step.key,
            "step_role": step.role,
        }

        if step_index == 0:
            # Step A — create v1 via the canonical service function.
            try:
                row = await create_deliverable_service(
                    db,
                    user_id=user_id,
                    project_id=project_id,
                    module_key=reg.module_key,
                    deliverable_type=deliverable_type,
                    title=title,
                    content=step_content,
                )
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "pipeline.create_failed type=%s step=%s err=%s — stopping chain",
                    deliverable_type, step.key, exc,
                )
                return None

            # Patch meta onto the freshly created row (v1 has meta=None from
            # create_deliverable_service; we update it here without bumping version).
            meta["chain_steps"].append({
                "key": step.key,
                "agent_name": step.agent_name,
                "role": step.role,
                "version": row.version,
            })
            meta["steps_completed"] = 1
            now = _utcnow()
            row.meta = meta.copy()
            row.updated_at = now
            await db.commit()
            await db.refresh(row)

            _log.info(
                "pipeline.step_complete type=%s step=%s version=%d deliverable_id=%s",
                deliverable_type, step.key, row.version, row.id,
            )
        else:
            # Step B+ — append a new version building on prior work.
            # Status is 'in_progress' until we reach the final step.
            is_last_step = (step_index == len(reg.steps) - 1)
            new_status = "awaiting_human" if is_last_step else "in_progress"

            meta["chain_steps"].append({
                "key": step.key,
                "agent_name": step.agent_name,
                "role": step.role,
                "version": row.version + 1,  # the version this step will produce
            })
            meta["steps_completed"] = step_index + 1

            try:
                await _append_version(
                    db,
                    row,
                    new_content=step_content,
                    new_status=new_status,
                    new_meta=meta.copy(),
                )
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "pipeline.append_version_failed type=%s step=%s deliverable_id=%s err=%s",
                    deliverable_type, step.key, row.id, exc,
                )
                # Leave at last good version — don't raise.
                return row

            _log.info(
                "pipeline.step_complete type=%s step=%s version=%d status=%s deliverable_id=%s",
                deliverable_type, step.key, row.version, row.status, row.id,
            )

        # Pass this step's output to the next step.
        prior_output = step_output

    # All steps completed. If there are more steps in Phase D, the chain stops
    # here with status='awaiting_human'. Return the final state.
    if row is not None:
        _log.info(
            "pipeline.chain_complete type=%s deliverable_id=%s version=%d status=%s steps=%d",
            deliverable_type, row.id, row.version, row.status, len(reg.steps),
        )
    return row
