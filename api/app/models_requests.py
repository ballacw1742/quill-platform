"""ORM model for project request submissions — Requests tab."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


# Terminal statuses an agent-cloud proposal may set on a request via
# `request_update`. Canonical source for the shared write-vocab contract
# (scripts/gen_write_vocab.py). The full lifecycle status set on RequestRecord
# is processing|complete|failed; only the two terminal values are settable by
# an approved agent write.
VALID_REQUEST_ACTION_STATUSES = ("complete", "failed")


class RequestRecord(Base):
    """A user-submitted project request (estimate, schedule, RFI, or contract)."""

    __tablename__ = "project_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )  # estimate | schedule | rfi | contract | general
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="processing",
        index=True,
    )  # processing | complete | failed
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_module: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # estimates | schedules | rfi | contracts
    output_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    drive_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    filenames: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # comma-separated original filenames
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
