"""ORM model for Quill Projects — Sprint DC.2."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, Float, String, Text
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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
