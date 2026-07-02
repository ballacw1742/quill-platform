"""ORM models for Quill Projects — Sprint DC.2 + 0.2 hardening."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


# Valid phase values
VALID_PHASES = (
    "site_control",
    "permitting",
    "design",
    "construction",
    "commissioning",
    "turnover",
)

# Valid status values
VALID_STATUSES = ("active", "on_hold", "complete", "cancelled")


class Project(Base):
    """A Quill project, optionally created from a DataSite site evaluation."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # DataSite linkage (nullable — standalone projects have no site)
    site_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )
    site_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    site_verdict: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    workload_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Pipeline state
    phase: Mapped[str] = mapped_column(
        String(50), nullable=False, default="site_control", index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", index=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Sprint 0.2 — budget fields
    budget_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    committed_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    forecast_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Sprint 0.2 — Milestones
# ---------------------------------------------------------------------------

class ProjectMilestone(Base):
    """A named milestone attached to a project."""

    __tablename__ = "project_milestones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Sprint 0.2 — Construction Log
# ---------------------------------------------------------------------------

# Valid entry_type values
VALID_ENTRY_TYPES = ("general", "issue", "milestone", "decision")


class ProjectLogEntry(Base):
    """A timestamped log entry (construction log / field notes)."""

    __tablename__ = "project_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    entry_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="general"
    )  # general | issue | milestone | decision
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )


# ---------------------------------------------------------------------------
# Sprint 0.2 — Document links
# ---------------------------------------------------------------------------


class ProjectDocumentLink(Base):
    """Soft link from a project to a document (internal doc_id or external URL)."""

    __tablename__ = "project_document_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Sprint 0.2 — Contract + Estimate links
# ---------------------------------------------------------------------------


class ProjectContractLink(Base):
    """Links a contract (by upload_id) to a project."""

    __tablename__ = "project_contract_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class ProjectEstimateLink(Base):
    """Links an estimate (by upload_id) to a project."""

    __tablename__ = "project_estimate_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    estimate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
