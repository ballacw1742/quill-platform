"""ORM models for Quill Sites — Sprint 2 (Drive document intake)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


# Intake status values
VALID_INTAKE_STATUSES = ("completed", "completed_with_errors", "failed")


class SiteDriveIntake(Base):
    """One Drive-folder document intake run for a site.

    Stores honest per-document results — each document the intake saw and
    what actually happened to it (indexed / uploaded / skipped / failed).
    """

    __tablename__ = "site_drive_intakes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    site_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    folder_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    requested_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    # completed | completed_with_errors | failed
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="failed")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # list[{file_id, filename, mime_type, size, status, detail, doc_type}]
    documents: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
