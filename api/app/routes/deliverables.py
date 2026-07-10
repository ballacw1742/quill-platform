"""Deliverables API — Phase A / G1.

Endpoints (all JWT-gated via get_current_user):

  POST   /v1/deliverables               create (any authed member)
  GET    /v1/deliverables               list own deliverables; ?project_id= optional
  GET    /v1/deliverables/{id}          detail; 404 if not owner or unknown
  PATCH  /v1/deliverables/{id}          update (title/status/content/change_action); bumps version
  GET    /v1/deliverables/{id}/versions list version history newest-first
  POST   /v1/deliverables/{id}/rollback rollback to a prior version

Phase G1 additions:
  POST   /v1/deliverables/{id}/codev    co-develop: propose a revision WITHOUT committing
  POST   /v1/deliverables/{id}/resume   resume chain after co-dev contribution

All records are user-scoped (user.id). No owner-role restriction in Phase A —
deliverables are per-user records open to any authenticated member.

Versioning mirrors agent-cloud Phase 5 semantics:
  - monotonic integer version starting at 1
  - immutable DeliverableVersion snapshot per version
  - rollback creates a NEW version (never destructive)
  - newest-first ordering on version history

Phase G1 change_action allowlist: updated | human_edited | co_developed
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.deliverable_registry import DELIVERABLE_REGISTRY
from app.models_deliverables import Deliverable, DeliverableVersion
from app.security import get_current_user

_log = logging.getLogger("quill.deliverables")

_settings = get_settings()
# ADK agents service URL — reuse the same env var as routes/requests.py.
ADK_URL: str = os.environ.get("ADK_AGENTS_URL", _settings.INTERNAL_API_URL)

# Default fallback agent name when the registry has no steps.
_DEFAULT_AGENT_NAME = "quill_coordinator"

router = APIRouter(prefix="/v1/deliverables", tags=["deliverables"])

# ── Allowed status values (free-string validation) ─────────────────────────────
ALLOWED_STATUSES = frozenset(
    {"draft", "in_progress", "awaiting_human", "approved", "rejected", "published", "superseded"}
)

# Phase G1: allowlist of caller-settable change_action values for PATCH.
ALLOWED_CHANGE_ACTIONS = frozenset({"updated", "human_edited", "co_developed"})

# ── Pydantic schemas ───────────────────────────────────────────────────────────


class DeliverableCreate(BaseModel):
    project_id: str | None = Field(default=None, max_length=36)
    module_key: str = Field(min_length=1, max_length=64)
    deliverable_type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    content: dict | None = None


class DeliverablePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: str | None = Field(default=None, max_length=24)
    content: dict | None = None
    # Phase G1: optional change_action; defaults to "updated" for backward compat.
    change_action: str | None = Field(default=None, max_length=24)


class RollbackIn(BaseModel):
    to_version: int = Field(ge=1)


# ── Phase G1 schemas ──────────────────────────────────────────────────────────


class CodevRequest(BaseModel):
    """Body for POST /v1/deliverables/{id}/codev."""
    prompt: str = Field(min_length=1, max_length=8000)
    current_content: dict | None = None


class ResumeRequest(BaseModel):
    """Body for POST /v1/deliverables/{id}/resume."""
    content: dict
    resume_chain: bool = True


# ── Response serialisers ───────────────────────────────────────────────────────


def _deliverable_out(d: Deliverable) -> dict:
    # Look up the stage_key from the registry (code-only metadata; no DB column).
    reg = DELIVERABLE_REGISTRY.get(d.deliverable_type)
    stage_key = reg.stage_key if reg is not None else ""
    # Phase G1: surface the Drive URL from the content/meta drive block.
    # Phase F stores {"drive": {"mode", "url", "doc_id"/"sheet_id", ...}} inside
    # the generated content record.  We surface a top-level convenience field so
    # the frontend doesn't have to dig.
    drive_url: str | None = None
    for blob in (d.content, d.meta):
        if isinstance(blob, dict):
            drive_block = blob.get("drive")
            if isinstance(drive_block, dict):
                url = drive_block.get("url")
                if url:
                    drive_url = url
                    break
    return {
        "id": d.id,
        "user_id": d.user_id,
        "project_id": d.project_id,
        "module_key": d.module_key,
        "deliverable_type": d.deliverable_type,
        "title": d.title,
        "status": d.status,
        "version": d.version,
        "content": d.content,
        "meta": d.meta,
        "stage_key": stage_key,
        "drive_url": drive_url,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
    }


def _version_out(v: DeliverableVersion) -> dict:
    return {
        "id": v.id,
        "deliverable_id": v.deliverable_id,
        "version": v.version,
        "title": v.title,
        "status": v.status,
        "content": v.content,
        "change_action": v.change_action,
        "created_at": v.created_at.isoformat(),
    }


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _get_own_deliverable(
    deliverable_id: str, user_id: str, db: AsyncSession
) -> Deliverable:
    """Fetch deliverable by id scoped to user_id; raise 404 if missing or
    belongs to another user."""
    row = (
        await db.execute(
            select(Deliverable).where(Deliverable.id == deliverable_id)
        )
    ).scalar_one_or_none()
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "deliverable not found")
    return row


def _snapshot(
    row: Deliverable,
    change_action: str,
    now: datetime,
) -> DeliverableVersion:
    """Create an immutable snapshot of the current deliverable state."""
    return DeliverableVersion(
        deliverable_id=row.id,
        version=row.version,
        title=row.title,
        status=row.status,
        content=row.content,
        change_action=change_action,
        created_at=now,
    )


# ── Service function (shared by route + deliverable producer) ─────────────────


async def create_deliverable_service(
    db: AsyncSession,
    *,
    user_id: str,
    project_id: str | None,
    module_key: str,
    deliverable_type: str,
    title: str,
    content: dict | None,
) -> Deliverable:
    """Create a Deliverable (v1) + its initial 'created' snapshot.

    This is the single code path for deliverable creation used by both the
    POST /v1/deliverables route and the background deliverable producer in
    routes/requests.py. Do NOT duplicate this logic elsewhere.

    Callers are responsible for supplying a valid db session and committing
    if they need to confirm persistence (this function commits internally).
    Returns the refreshed Deliverable ORM row.
    """
    now = datetime.now(UTC)
    row = Deliverable(
        user_id=user_id,
        project_id=project_id,
        module_key=module_key,
        deliverable_type=deliverable_type,
        title=title,
        status="draft",
        version=1,
        content=content,
        meta=None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()  # populate row.id before snapshot references it
    snap = _snapshot(row, "created", now)
    db.add(snap)
    await db.commit()
    await db.refresh(row)
    _log.info(
        "deliverable.created id=%s type=%s module=%s user=%s",
        row.id, deliverable_type, module_key, user_id,
    )
    return row


async def append_deliverable_version_service(
    db: AsyncSession,
    row: Deliverable,
    *,
    title: str | None = None,
    status: str | None = None,
    content: dict | None = None,
    meta: dict | None = None,
    change_action: str = "updated",
) -> Deliverable:
    """Append a new version to an existing Deliverable (the SINGLE shared path).

    Used by the PATCH route, the pipeline orchestrator, and rollback. Applies
    any provided fields, bumps the version, THEN snapshots the new state so the
    snapshot's version number matches its content (one snapshot per version,
    mirroring agent-cloud Phase 5). Never destructive. Commits + refreshes.
    Only fields passed (not None) are changed; meta replaces when provided.
    """
    now = datetime.now(UTC)
    if title is not None:
        row.title = title
    if status is not None:
        row.status = status
    if content is not None:
        row.content = content
    if meta is not None:
        row.meta = meta
    row.version = row.version + 1
    row.updated_at = now
    snap = _snapshot(row, change_action, now)
    db.add(snap)
    await db.commit()
    await db.refresh(row)
    return row


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_deliverable(
    body: DeliverableCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Create a new deliverable (any authenticated member). Returns v1."""
    row = await create_deliverable_service(
        db,
        user_id=user.id,
        project_id=body.project_id,
        module_key=body.module_key,
        deliverable_type=body.deliverable_type,
        title=body.title,
        content=body.content,
    )
    return _deliverable_out(row)


@router.get("")
async def list_deliverables(
    project_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """List the caller's deliverables, newest-first. Optionally filter by
    project_id."""
    q = select(Deliverable).where(Deliverable.user_id == user.id)
    if project_id is not None:
        q = q.where(Deliverable.project_id == project_id)
    q = q.order_by(Deliverable.created_at.desc())
    rows = (await db.execute(q)).scalars().all()
    return {"items": [_deliverable_out(r) for r in rows], "total": len(rows)}


@router.get("/{deliverable_id}")
async def get_deliverable(
    deliverable_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Fetch one deliverable. 404 if not the owner or unknown."""
    row = await _get_own_deliverable(deliverable_id, user.id, db)
    return _deliverable_out(row)


@router.patch("/{deliverable_id}")
async def update_deliverable(
    deliverable_id: str,
    body: DeliverablePatch,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Update title/status/content. Bumps version and appends a version snapshot.

    Phase G1: ``change_action`` is now an optional request body field.
    Allowed values: ``updated`` (default), ``human_edited``, ``co_developed``.
    Never destructive.
    """
    if body.status is not None and body.status not in ALLOWED_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid status {body.status!r}; allowed: {sorted(ALLOWED_STATUSES)}",
        )
    # Phase G1: validate and resolve change_action
    eff_change_action = body.change_action if body.change_action is not None else "updated"
    if eff_change_action not in ALLOWED_CHANGE_ACTIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid change_action {eff_change_action!r}; allowed: {sorted(ALLOWED_CHANGE_ACTIONS)}",
        )
    row = await _get_own_deliverable(deliverable_id, user.id, db)
    # Single shared version-append path (also used by the pipeline orchestrator).
    row = await append_deliverable_version_service(
        db, row,
        title=body.title,
        status=body.status,
        content=body.content,
        change_action=eff_change_action,
    )
    return _deliverable_out(row)


@router.get("/{deliverable_id}/versions")
async def list_versions(
    deliverable_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """List all version snapshots for a deliverable, newest-first. 404 if not
    the owner or unknown."""
    # Ownership check via the live head.
    await _get_own_deliverable(deliverable_id, user.id, db)
    snaps = (
        await db.execute(
            select(DeliverableVersion)
            .where(DeliverableVersion.deliverable_id == deliverable_id)
            .order_by(DeliverableVersion.version.desc())
        )
    ).scalars().all()
    return {"items": [_version_out(s) for s in snaps], "total": len(snaps)}


@router.post("/{deliverable_id}/rollback", status_code=status.HTTP_200_OK)
async def rollback_deliverable(
    deliverable_id: str,
    body: RollbackIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Rollback to a prior version. Restores that version's title/status/content
    as a NEW version (never destructive). 404 if the version is unknown."""
    row = await _get_own_deliverable(deliverable_id, user.id, db)

    # One snapshot per version number (created at v1, one per PATCH/rollback).
    # .limit(1) is defensive only.
    target_snap = (
        await db.execute(
            select(DeliverableVersion)
            .where(
                DeliverableVersion.deliverable_id == deliverable_id,
                DeliverableVersion.version == body.to_version,
            )
            .order_by(DeliverableVersion.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if target_snap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")

    now = datetime.now(UTC)
    # Apply the rolled-back fields to the live head.
    row.title = target_snap.title
    row.status = target_snap.status
    row.content = target_snap.content
    row.version = row.version + 1
    row.updated_at = now

    # Snapshot the new (rolled-back) state.
    snap = _snapshot(row, "rolledback", now)
    db.add(snap)

    await db.commit()
    await db.refresh(row)
    return _deliverable_out(row)


# ---------------------------------------------------------------------------
# Phase G1: injectable ADK call helper (monkeypatchable in tests)
# ---------------------------------------------------------------------------

async def _call_codev_agent(
    endpoint: str,
    payload: dict,
    agent_id: str,
    deliverable_id: str,
) -> httpx.Response:
    """POST to the ADK agent for a co-dev call.

    This is a module-level async function so tests can monkeypatch it without
    touching HTTP.  Mirrors the pattern in routes/requests.py
    (_call_adk_with_retry).  A single attempt — callers handle 502 on error.
    """
    async with httpx.AsyncClient(timeout=120) as hclient:
        resp = await hclient.post(endpoint, json=payload)
    return resp


# ---------------------------------------------------------------------------
# Phase G1: co-development endpoints
# ---------------------------------------------------------------------------


@router.post("/{deliverable_id}/codev", status_code=status.HTTP_200_OK)
async def codev_deliverable(
    deliverable_id: str,
    body: CodevRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Propose an AI revision without committing (Phase G1 co-dev endpoint).

    Dispatches the deliverable's owning-module agent via ADK /invoke using the
    same pattern as routes/requests.py.  Returns a **proposed** revised content
    dict WITHOUT bumping the version or changing any stored state.

    The caller inspects ``proposed_content``, may edit it, and then either:
      - calls ``PATCH /v1/deliverables/{id}`` with ``change_action="co_developed"``
        to commit the accepted revision, or
      - calls ``POST /v1/deliverables/{id}/resume`` to commit + optionally
        resume the pipeline chain.

    Fail-safe: any ADK/agent error returns HTTP 502 and leaves the live
    deliverable completely untouched (no writes).
    """
    row = await _get_own_deliverable(deliverable_id, user.id, db)

    # Resolve agent name from registry; fall back to default coordinator.
    reg = DELIVERABLE_REGISTRY.get(row.deliverable_type)
    agent_name: str
    if reg is not None and reg.steps:
        agent_name = reg.steps[-1].agent_name
    else:
        agent_name = _DEFAULT_AGENT_NAME

    # Build the prompt for the ADK agent.
    current = body.current_content if body.current_content is not None else (row.content or {})
    import json as _json
    prompt = (
        f"You are co-developing a {row.deliverable_type} deliverable titled "
        f"\"{row.title}\". The human contributor says:\n\n{body.prompt}\n\n"
        f"Current content (version {row.version}):\n{_json.dumps(current, indent=2)}\n\n"
        f"Produce a revised version of the deliverable content that incorporates "
        f"the human's contribution. Return ONLY a JSON object representing the "
        f"new content — do not include markdown fences or commentary."
    )

    adk_ep = f"{ADK_URL}/invoke"
    adk_payload = {
        "agent": agent_name,
        "message": prompt,
        "session_id": f"codev-{deliverable_id}",
    }

    _log.info(
        "codev.dispatch deliverable_id=%s agent=%s version=%d",
        deliverable_id, agent_name, row.version,
    )

    # Make the ADK call — any error → 502, deliverable untouched.
    try:
        resp = await _call_codev_agent(adk_ep, adk_payload, agent_name, deliverable_id)
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "codev.adk_error deliverable_id=%s agent=%s err=%s",
            deliverable_id, agent_name, exc,
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Agent call failed: {exc!s}",
        ) from exc

    if resp.status_code >= 400:
        _log.warning(
            "codev.adk_bad_status deliverable_id=%s agent=%s status=%d body=%s",
            deliverable_id, agent_name, resp.status_code, resp.text[:500],
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Agent returned {resp.status_code}: {resp.text[:200]}",
        )

    # Parse the agent response.
    agent_text: str = ""
    try:
        resp_body = resp.json()
        if isinstance(resp_body, dict):
            agent_text = (
                resp_body.get("response") or
                resp_body.get("output") or
                resp_body.get("content") or
                str(resp_body)
            )
        else:
            agent_text = str(resp_body)
    except Exception:  # noqa: BLE001
        agent_text = resp.text[:4000]

    # Try to parse the agent response as JSON content.
    # If the agent returns a JSON object, use it as proposed_content.
    # Otherwise, wrap the text in a {"summary": ...} envelope.
    proposed_content: dict
    try:
        # Strip markdown fences if present.
        stripped = agent_text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            # Remove first and last fence lines.
            lines = [l for l in lines if not l.startswith("```")]
            stripped = "\n".join(lines).strip()
        parsed = _json.loads(stripped)
        if isinstance(parsed, dict):
            proposed_content = parsed
        else:
            proposed_content = {"summary": agent_text, "raw_response": parsed}
    except Exception:  # noqa: BLE001
        proposed_content = {"summary": agent_text}

    # Extract a short summary for the response.
    proposed_summary: str | None = (
        proposed_content.get("summary") or proposed_content.get("response")
        if isinstance(proposed_content, dict) else None
    )
    if isinstance(proposed_summary, str):
        proposed_summary = proposed_summary[:500]

    _log.info(
        "codev.proposed deliverable_id=%s version=%d keys=%s",
        deliverable_id, row.version, list(proposed_content.keys()),
    )

    return {
        "proposed_content": proposed_content,
        "proposed_summary": proposed_summary,
        "based_on_version": row.version,
    }


@router.post("/{deliverable_id}/resume", status_code=status.HTTP_200_OK)
async def resume_deliverable(
    deliverable_id: str,
    body: ResumeRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Apply human-accepted content and optionally resume the pipeline chain.

    Phase G1/G4 resume endpoint — resolves a co-development ``awaiting_human`` gate.

    1. Applies ``body.content`` via ``append_deliverable_version_service`` with
       ``change_action="co_developed"``.
    2. Status transition:
       - If ``resume_chain=True``: status → ``in_progress`` (chain continues).
       - If ``resume_chain=False``: status → ``approved`` (human accepted; done).
    3. Phase G4: if ``resume_chain=True`` AND the deliverable_type has remaining
       chain steps after the current ``steps_completed`` count, re-invokes
       ``run_deliverable_chain`` with ``start_step_index=steps_completed`` and
       ``existing_row`` set to the live deliverable. The chain runs remaining
       steps on the existing row without re-creating it.

    Fail-safe: a chain error during resume leaves the deliverable at its last-good
    version (the human-accepted content already appended). The endpoint returns 200
    with the current deliverable state regardless of chain outcome.
    """
    row = await _get_own_deliverable(deliverable_id, user.id, db)

    # Determine target status.
    new_status = "in_progress" if body.resume_chain else "approved"

    # Build updated meta: clear the co-dev gate flag, record the human action.
    existing_meta = dict(row.meta or {})
    existing_meta["co_dev_resume"] = {
        "resumed_from_version": row.version,
        "resume_chain": body.resume_chain,
    }
    # Keep hitl_kind in meta but mark as resolved.
    existing_meta["hitl_resolved"] = True

    try:
        row = await append_deliverable_version_service(
            db,
            row,
            content=body.content,
            status=new_status,
            meta=existing_meta,
            change_action="co_developed",
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "resume.append_failed deliverable_id=%s err=%s — deliverable left untouched",
            deliverable_id, exc,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to apply resumed content; deliverable unchanged.",
        ) from exc

    _log.info(
        "resume.ok deliverable_id=%s new_version=%d new_status=%s resume_chain=%s",
        deliverable_id, row.version, new_status, body.resume_chain,
    )

    # Phase G4: mid-chain resume — actually resume the chain from the next step.
    if body.resume_chain:
        reg = DELIVERABLE_REGISTRY.get(row.deliverable_type)
        if reg is not None and reg.steps:
            steps_completed = (row.meta or {}).get("steps_completed", 0)
            remaining = len(reg.steps) - steps_completed
            if remaining > 0:
                _log.info(
                    "resume.chain_continue deliverable_id=%s type=%s steps_completed=%d/%d — "
                    "invoking run_deliverable_chain from step %d",
                    deliverable_id, row.deliverable_type, steps_completed, len(reg.steps),
                    steps_completed,
                )
                # Build the ADK call_agent helper using the same pattern as routes/requests.py.
                seed_message: str = (
                    (row.content or {}).get("seed_message", row.title)
                    if isinstance(row.content, dict) else row.title
                ) or row.title

                async def _chain_call_agent(agent_name: str, msg: str) -> str:
                    adk_ep = f"{ADK_URL}/invoke"
                    adk_pl = {
                        "agent": agent_name,
                        "message": msg,
                        "session_id": f"resume-{deliverable_id}",
                    }
                    try:
                        resp = await _call_codev_agent(
                            adk_ep, adk_pl, agent_name, deliverable_id
                        )
                        if resp.status_code < 400:
                            try:
                                b = resp.json()
                                return (
                                    b.get("response", "") if isinstance(b, dict) else str(b)
                                )
                            except Exception:  # noqa: BLE001
                                return resp.text[:2000]
                        return f"ADK agent returned {resp.status_code}: {resp.text[:500]}"
                    except Exception as exc:  # noqa: BLE001
                        raise RuntimeError(f"Agent call failed: {exc}") from exc

                # Import here to avoid circular import at module level.
                from app.deliverable_pipeline import run_deliverable_chain
                from app.db import SessionLocal as _resume_session_maker  # noqa: N812

                try:
                    async with _resume_session_maker() as chain_session:
                        # Reload the row in the new session to avoid detached-instance errors.
                        from sqlalchemy import select as _select
                        chain_row = (
                            await chain_session.execute(
                                _select(
                                    __import__(
                                        'app.models_deliverables',
                                        fromlist=['Deliverable'],
                                    ).Deliverable
                                ).where(
                                    __import__(
                                        'app.models_deliverables',
                                        fromlist=['Deliverable'],
                                    ).Deliverable.id == deliverable_id
                                )
                            )
                        ).scalar_one_or_none()
                        if chain_row is not None:
                            resumed_row = await run_deliverable_chain(
                                chain_session,
                                user_id=chain_row.user_id,
                                project_id=chain_row.project_id,
                                deliverable_type=chain_row.deliverable_type,
                                seed_message=seed_message,
                                call_agent=_chain_call_agent,
                                start_step_index=steps_completed,
                                existing_row=chain_row,
                            )
                            if resumed_row is not None:
                                # Reload the head row in the original session for the response.
                                await db.refresh(row)
                                _log.info(
                                    "resume.chain_done deliverable_id=%s new_version=%d new_status=%s",
                                    deliverable_id, resumed_row.version, resumed_row.status,
                                )
                except Exception as chain_exc:  # noqa: BLE001
                    # Chain error: leave the deliverable at its last-good version.
                    # Fail-safe: endpoint still returns 200 with current state.
                    _log.warning(
                        "resume.chain_error deliverable_id=%s err=%s — "
                        "deliverable left at last-good version; returning 200",
                        deliverable_id, chain_exc,
                    )
            else:
                _log.info(
                    "resume.no_remaining_steps deliverable_id=%s type=%s steps_completed=%d/%d — "
                    "no more steps to run",
                    deliverable_id, row.deliverable_type, steps_completed, len(reg.steps),
                )

    # Refresh to get latest state (chain may have appended versions).
    try:
        await db.refresh(row)
    except Exception:  # noqa: BLE001
        pass  # If refresh fails, return the last known state.

    return _deliverable_out(row)
