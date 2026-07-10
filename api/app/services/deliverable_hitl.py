"""Deliverable HITL (Human-In-The-Loop) service — Phase D / G1.

When ``run_deliverable_chain`` completes and leaves a Deliverable at status
``awaiting_human``, the caller invokes ``create_deliverable_approval`` to
create an ApprovalItem in the Approvals Queue.  The human then decides via the
normal Approvals UI/API; on execution, ``finalize_deliverable_on_approval`` is
called to transition the Deliverable to its final state.

Phase G1 adds **hitl_kind** — a field stored in ``deliverable.meta`` that
distinguishes two gate variants:

  ``"decision"``      — binary approve/reject gate (Phase D, existing behavior).
                        Routes to the Approvals Queue. ApprovalItem is created.
  ``"co_development"`` — human contributes unique context via the co-dev UI.
                         No ApprovalItem is created; resolved via
                         ``POST /v1/deliverables/{id}/resume``.

Backward compatibility: when ``hitl_kind`` is absent in meta, it defaults to
``"decision"`` (existing behaviour unchanged).

Design decisions:
  - Workflow: ``DELIVERABLE_ACCEPT_WORKFLOW`` (``"deliverable.accept"``)
  - Lane: ``Lane.SINGLE`` (owner single-sig) — never auto-execute (never Lane 1)
  - The deliverable_id is stored in the approval payload so the execute hook can
    find it without a separate join.
  - Fail-safe: approval-creation errors must NOT fail the request (callers wrap
    in try/except and log+continue).
  - On approval → deliverable status ``"approved"`` + new version via the shared
    ``append_deliverable_version_service``.
  - On rejection  → deliverable status ``"rejected"`` + new version recording
    the rejection note.
  - Idempotent on execute: if the deliverable has already left
    ``awaiting_human``, the hook logs and returns without re-applying.

Public G1 helpers:
  ``get_hitl_kind(deliverable)``  — read hitl_kind from meta; default "decision".
  ``set_hitl_kind(meta, kind)``   — return updated meta dict with hitl_kind set.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import DELIVERABLE_ACCEPT_WORKFLOW, Lane, Priority, UserRole
from app.models_deliverables import Deliverable
from app.routes.deliverables import append_deliverable_version_service

if TYPE_CHECKING:
    from app.models import ApprovalItem

_log = logging.getLogger("quill.deliverable_hitl")

# Sentinel agent_id for deliverable-gate approvals.  Must be non-empty and
# present in the create_approval call; the approvals service allows ad-hoc
# agent_ids that aren't in AGENT_FLEET (it warns but doesn't raise).
_DELIVERABLE_AGENT_ID = "deliverable-hitl"

# ---------------------------------------------------------------------------
# hitl_kind helpers (Phase G1)
# ---------------------------------------------------------------------------

#: The two recognised HITL gate kinds.
HITL_KIND_DECISION = "decision"
HITL_KIND_CO_DEVELOPMENT = "co_development"

_VALID_HITL_KINDS = frozenset({HITL_KIND_DECISION, HITL_KIND_CO_DEVELOPMENT})


def get_hitl_kind(deliverable: "Deliverable") -> str:
    """Return the hitl_kind stored in deliverable.meta.

    Defaults to ``"decision"`` when unset so existing deliverables are
    unaffected (backward-compatible).
    """
    meta = deliverable.meta or {}
    kind = meta.get("hitl_kind", HITL_KIND_DECISION)
    if kind not in _VALID_HITL_KINDS:
        _log.warning(
            "deliverable_hitl.unknown_kind deliverable_id=%s kind=%r — defaulting to 'decision'",
            deliverable.id, kind,
        )
        return HITL_KIND_DECISION
    return kind  # type: ignore[return-value]


def set_hitl_kind(meta: dict | None, kind: str) -> dict:
    """Return a (shallow-copied) meta dict with hitl_kind set.

    Parameters
    ----------
    meta:
        Existing meta dict (or None).
    kind:
        Either ``"decision"`` or ``"co_development"``.

    Returns
    -------
    dict
        Updated copy of meta (the original is not mutated).
    """
    if kind not in _VALID_HITL_KINDS:
        raise ValueError(f"hitl_kind must be one of {_VALID_HITL_KINDS!r}; got {kind!r}")
    updated = dict(meta or {})
    updated["hitl_kind"] = kind
    return updated


# ---------------------------------------------------------------------------
# Create approval for a deliverable gate
# ---------------------------------------------------------------------------

async def create_deliverable_approval(
    db: AsyncSession,
    deliverable: Deliverable,
    *,
    actor: str,
    summary: str | None = None,
) -> "ApprovalItem | None":
    """Create an ApprovalItem for a deliverable HITL gate.

    Parameters
    ----------
    db:
        Async session — caller manages lifecycle.
    deliverable:
        The Deliverable row at status ``awaiting_human``.
    actor:
        ID of the actor creating the approval (typically the user who owns the
        deliverable, or a system actor for background-task origins).
    summary:
        Short summary of what the agents produced and what the human must
        decide.  If omitted, a generic summary is built from the deliverable
        title and type.

    Returns
    -------
    ApprovalItem | None
        The newly created (and committed) approval row, or ``None`` when the
        gate is a **co_development** gate (those are resolved via
        ``POST /v1/deliverables/{id}/resume``, not the Approvals Queue).

    Notes
    -----
    - Lane.SINGLE (2) — never auto-execute.
    - Workflow = ``DELIVERABLE_ACCEPT_WORKFLOW``.
    - Payload carries ``deliverable_id``, ``deliverable_type``, ``title``,
      ``summary`` so the execute hook can resolve the deliverable without a
      separate query.
    - Phase G1: if ``meta.hitl_kind == "co_development"``, this function logs
      and returns ``None`` without creating an ApprovalItem.  Decision gates
      (the default) are unchanged.
    """
    # Phase G1: co_development gates do NOT create an ApprovalItem.
    kind = get_hitl_kind(deliverable)
    if kind == HITL_KIND_CO_DEVELOPMENT:
        _log.info(
            "deliverable_hitl.skip_approval_for_co_dev deliverable_id=%s — co_development gate",
            deliverable.id,
        )
        return None

    from app.services.approvals import create_approval

    eff_summary = summary or (
        f"Review the AI-produced {deliverable.deliverable_type} deliverable "
        f"\"{deliverable.title}\" and approve or reject it."
    )

    payload = {
        "agent_id": _DELIVERABLE_AGENT_ID,
        "agent_version": "phase-d",
        "workflow": DELIVERABLE_ACCEPT_WORKFLOW,
        "lane": Lane.SINGLE.value,
        "priority": Priority.NORMAL.value,
        "target_system": "none",
        "required_approvers": [UserRole.OWNER.value],
        "payload": {
            "deliverable_id": deliverable.id,
            "deliverable_type": deliverable.deliverable_type,
            "title": deliverable.title,
            "summary": eff_summary,
        },
        "agent_reasoning": eff_summary,
    }

    item = await create_approval(db, payload=payload, actor=actor)
    _log.info(
        "deliverable_hitl.approval_created deliverable_id=%s approval_id=%s workflow=%s lane=%d",
        deliverable.id, item.id, item.workflow, item.lane,
    )
    return item


# ---------------------------------------------------------------------------
# Finalize deliverable on approval execution
# ---------------------------------------------------------------------------

async def finalize_deliverable_on_approval(
    db: AsyncSession,
    approval_item: "ApprovalItem",
    *,
    actor: str,
    approved: bool,
    rejection_reason: str | None = None,
) -> Deliverable | None:
    """Finalize a deliverable after its HITL approval is executed/rejected.

    Called from the execute_approval hook in approvals.py when an approval of
    workflow ``deliverable.accept`` transitions to EXECUTED (approved) or
    REJECTED.

    Parameters
    ----------
    db:
        Async session.
    approval_item:
        The ApprovalItem that was just decided.
    actor:
        Approver's ID (for audit trail on the new version).
    approved:
        True  → deliverable becomes ``"approved"``
        False → deliverable becomes ``"rejected"``
    rejection_reason:
        Optional human note recorded in the version meta on rejection.

    Returns
    -------
    Deliverable | None
        The updated Deliverable row, or None if the deliverable couldn't be
        found or was already finalized.
    """
    payload = approval_item.payload or {}
    deliverable_id = payload.get("deliverable_id")
    if not deliverable_id:
        _log.warning(
            "deliverable_hitl.finalize_missing_id approval_id=%s payload=%r",
            approval_item.id, payload,
        )
        return None

    row: Deliverable | None = await db.get(Deliverable, str(deliverable_id))
    if row is None:
        _log.warning(
            "deliverable_hitl.finalize_not_found deliverable_id=%s approval_id=%s",
            deliverable_id, approval_item.id,
        )
        return None

    # Idempotent: if already finalized, skip.
    if row.status not in ("awaiting_human",):
        _log.info(
            "deliverable_hitl.finalize_already_done deliverable_id=%s status=%s — skipping",
            deliverable_id, row.status,
        )
        return row

    new_status = "approved" if approved else "rejected"
    decision_meta = {
        "decision": "approved" if approved else "rejected",
        "approval_id": approval_item.id,
        "decided_by": actor,
    }
    if rejection_reason:
        decision_meta["rejection_reason"] = rejection_reason

    # Merge decision meta into the existing chain meta.
    existing_meta = dict(row.meta or {})
    existing_meta["human_decision"] = decision_meta

    try:
        row = await append_deliverable_version_service(
            db,
            row,
            status=new_status,
            meta=existing_meta,
            change_action="updated",
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "deliverable_hitl.finalize_append_failed deliverable_id=%s approval_id=%s err=%s",
            deliverable_id, approval_item.id, exc,
        )
        return row

    _log.info(
        "deliverable_hitl.finalize_ok deliverable_id=%s approval_id=%s new_status=%s version=%d",
        deliverable_id, approval_item.id, new_status, row.version,
    )
    return row
