"""Deliverables API — Phase A (deliverable spine).

Endpoints (all JWT-gated via get_current_user):

  POST   /v1/deliverables          create (any authed member)
  GET    /v1/deliverables          list own deliverables; ?project_id= optional
  GET    /v1/deliverables/{id}     detail; 404 if not owner or unknown
  PATCH  /v1/deliverables/{id}     update (title/status/content); bumps version
  GET    /v1/deliverables/{id}/versions  list version history newest-first
  POST   /v1/deliverables/{id}/rollback  rollback to a prior version

All records are user-scoped (user.id). No owner-role restriction in Phase A —
deliverables are per-user records open to any authenticated member.

Versioning mirrors agent-cloud Phase 5 semantics:
  - monotonic integer version starting at 1
  - immutable DeliverableVersion snapshot per version
  - rollback creates a NEW version (never destructive)
  - newest-first ordering on version history
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models_deliverables import Deliverable, DeliverableVersion
from app.security import get_current_user

import logging
_log = logging.getLogger("quill.deliverables")

router = APIRouter(prefix="/v1/deliverables", tags=["deliverables"])

# ── Allowed status values (free-string validation) ─────────────────────────────
ALLOWED_STATUSES = frozenset(
    {"draft", "in_progress", "awaiting_human", "approved", "published", "superseded"}
)

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


class RollbackIn(BaseModel):
    to_version: int = Field(ge=1)


# ── Response serialisers ───────────────────────────────────────────────────────


def _deliverable_out(d: Deliverable) -> dict:
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
    """Update title/status/content. Bumps version and appends an 'updated'
    DeliverableVersion snapshot. Never destructive."""
    if body.status is not None and body.status not in ALLOWED_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid status {body.status!r}; allowed: {sorted(ALLOWED_STATUSES)}",
        )
    row = await _get_own_deliverable(deliverable_id, user.id, db)

    now = datetime.now(UTC)
    # Apply changes and bump the version FIRST, then snapshot the NEW state so
    # the snapshot's version number matches its content (one snapshot per
    # version, mirroring agent-cloud Phase 5). v1's snapshot was written at
    # create time; each PATCH writes the snapshot for the version it produces.
    if body.title is not None:
        row.title = body.title
    if body.status is not None:
        row.status = body.status
    if body.content is not None:
        row.content = body.content
    row.version = row.version + 1
    row.updated_at = now

    snap = _snapshot(row, "updated", now)
    db.add(snap)

    await db.commit()
    await db.refresh(row)
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
