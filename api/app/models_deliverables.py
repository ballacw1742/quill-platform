"""ORM models for the Deliverable entity — Phase A (deliverable spine).

Two tables:
  deliverables            — live head record (mutable, versioned monotonically)
  deliverable_versions    — immutable snapshots (one per version per deliverable)

Versioning semantics mirror agent-cloud AgentVersion:
  - version starts at 1 on create
  - every mutating PATCH bumps version and appends a DeliverableVersion row
    capturing the PRIOR state (change_action="updated")
  - rollback restores a past version's fields as a NEW version
    (change_action="rolledback")
  - snapshots are insert-only; never mutated or hard-deleted

Design decisions (Phase A — purely additive):
  - user_id scoped (user-owned records; no workspace/tenant indirection yet)
  - project_id nullable (deliverables can exist outside a project in Phase A)
  - status is a free String (no DB enum) so future values don't require a
    migration; allowed values validated at the route layer
  - content/meta are JSON blobs (artifact body + lineage placeholders)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Deliverable(Base):
    """Live head of a deliverable artifact.

    Mutable: PATCH bumps `version` and writes a DeliverableVersion snapshot of
    the prior state before applying the new fields. The head always reflects
    the current (highest) version.

    Status vocabulary (free-string; validated at route layer):
        draft | in_progress | awaiting_human | approved | published | superseded
    """

    __tablename__ = "deliverables"
    __table_args__ = (
        Index("ix_deliverables_user_id", "user_id"),
        Index("ix_deliverables_project_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    module_key: Mapped[str] = mapped_column(String(64), nullable=False)
    deliverable_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class DeliverableVersion(Base):
    """Immutable version snapshot for a deliverable.

    Written whenever the live Deliverable row changes:
      - created   — initial row written on POST (version 1 snapshot)
      - updated   — snapshot of state BEFORE a PATCH is applied
      - rolledback — snapshot written when rolling back; records the new state

    Never mutated, never hard-deleted. Newest-first for history queries.
    """

    __tablename__ = "deliverable_versions"
    __table_args__ = (
        Index("ix_deliverable_versions_deliverable_id", "deliverable_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    deliverable_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # created | updated | rolledback
    change_action: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
