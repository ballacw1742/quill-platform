"""SQLAlchemy 2.0 ORM models for the Dev Chat module (Sprint DC.1).

Three tables:
  dev_chat_threads  — one per user; tracks idle/in_progress state.
  dev_chat_messages — conversation history; roles: user | agent | system.
  dev_chat_tasks    — OpenClaw sub-agent task briefs; status lifecycle.

Conventions follow models.py exactly (mapped_column, Mapped, _uuid helper,
JSONType selection for SQLite vs Postgres, index via __table_args__).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.db import Base

_settings = get_settings()

if _settings.is_sqlite:
    JSONType = JSON
else:
    from sqlalchemy.dialects.postgresql import JSONB  # type: ignore
    JSONType = JSONB  # type: ignore[assignment]


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# DevChatThread
# ---------------------------------------------------------------------------
class DevChatThread(Base):
    """One thread per user.  State machine: idle ↔ in_progress."""

    __tablename__ = "dev_chat_threads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    """'idle' | 'in_progress'"""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    messages: Mapped[list[DevChatMessage]] = relationship(
        "DevChatMessage",
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="DevChatMessage.created_at",
    )
    tasks: Mapped[list[DevChatTask]] = relationship(
        "DevChatTask",
        back_populates="thread",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# DevChatMessage
# ---------------------------------------------------------------------------
class DevChatMessage(Base):
    """A single message in the dev-chat thread.

    role:   user | agent | system
    status: queued | streaming | completed | failed | cancelled
    """

    __tablename__ = "dev_chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dev_chat_threads.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    """'user' | 'agent' | 'system'"""

    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONType, nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    """'queued' | 'streaming' | 'completed' | 'failed' | 'cancelled'"""

    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    files_changed: Mapped[list[Any] | None] = mapped_column(JSONType, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    thread: Mapped[DevChatThread] = relationship("DevChatThread", back_populates="messages")

    __table_args__ = (
        Index("ix_dev_chat_messages_thread_created", "thread_id", "created_at"),
    )


# ---------------------------------------------------------------------------
# DevChatTask
# ---------------------------------------------------------------------------
class DevChatTask(Base):
    """Task brief for an OpenClaw sub-agent.

    id == task_id (UUID written to ~/.openclaw/dev-chat-queue/<id>.task.json)

    status: queued | running | completed | failed | cancelled
    """

    __tablename__ = "dev_chat_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dev_chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dev_chat_threads.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    branch: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    """'queued' | 'running' | 'completed' | 'failed' | 'cancelled'"""

    budget_usd_cap: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal("2.0"))
    disallowed_paths: Mapped[list[Any] | None] = mapped_column(JSONType, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    thread: Mapped[DevChatThread] = relationship("DevChatThread", back_populates="tasks")

    __table_args__ = (
        Index("ix_dev_chat_tasks_status", "status"),
    )


__all__ = ["DevChatThread", "DevChatMessage", "DevChatTask"]
