"""ORM models for the agentcloud_* tables.

Table shapes match the spike DDL (agent-cloud spike, merged 5d82f4d) plus
additive A1 columns. Postgres DDL is applied by app/migrations.py (raw SQL,
additive-only); these models mirror it and drive sqlite create_all in tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, date

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

JSONVariant = sa.JSON().with_variant(JSONB(), "postgresql")
BigIntPK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "agentcloud_tenants"

    tenant_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


class AgentDef(Base):
    """An agent is data, not code (design doc §3.3)."""

    __tablename__ = "agentcloud_agents"

    tenant_id: Mapped[str] = mapped_column(
        sa.Text, sa.ForeignKey("agentcloud_tenants.tenant_id"), primary_key=True
    )
    agent_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    system_prompt: Mapped[str] = mapped_column(sa.Text, nullable=False)
    model: Mapped[str] = mapped_column(sa.Text, nullable=False)
    tools: Mapped[list] = mapped_column(JSONVariant, nullable=False, default=list)
    budget_monthly_usd: Mapped[float] = mapped_column(
        sa.Numeric(10, 2), nullable=False, default=20.0
    )
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    # off | tools_only | auto_recall (A2 memory subsystem)
    memory_policy: Mapped[str] = mapped_column(sa.Text, nullable=False, default="off")
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


class Session(Base):
    __tablename__ = "agentcloud_sessions"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agentcloud_agents.tenant_id", "agentcloud_agents.agent_id"],
        ),
        sa.Index("agentcloud_sessions_tenant_idx", "tenant_id", "agent_id"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    agent_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


class Message(Base):
    __tablename__ = "agentcloud_messages"
    __table_args__ = (
        sa.Index("agentcloud_messages_session_idx", "tenant_id", "session_id", "message_id"),
    )

    message_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("agentcloud_sessions.session_id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    role: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content: Mapped[object] = mapped_column(JSONVariant, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


class MemoryRow(Base):
    """Long-term memory, namespaced by (tenant, agent) (design doc §3.2).

    The pgvector `embedding vector(<dim>)` column is intentionally NOT mapped
    here: it only exists on Postgres when the pgvector extension is available
    (added by migrations), and all vector reads/writes go through raw SQL in
    app/memory.py. sqlite (tests) uses this ORM shape + text-search fallback.
    """

    __tablename__ = "agentcloud_memory"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agentcloud_agents.tenant_id", "agentcloud_agents.agent_id"],
        ),
        sa.Index("agentcloud_memory_tenant_idx", "tenant_id", "agent_id", "kind"),
    )

    memory_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    agent_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False, default="fact")
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    meta: Mapped[dict] = mapped_column(
        "metadata", JSONVariant, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_accessed: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class EventRow(Base):
    """Durable copy of every published event (EVENTS.md). event_id is the
    idempotency key; the bus is notification, this table is truth."""

    __tablename__ = "agentcloud_events"
    __table_args__ = (
        sa.Index("agentcloud_events_tenant_idx", "tenant_id", "created_at"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    agent_id: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    session_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONVariant, nullable=False, default=dict)
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


class Job(Base):
    """Sub-agent job row (EVENTS.md §jobs). status: queued|running|ok|error|timeout."""

    __tablename__ = "agentcloud_jobs"
    __table_args__ = (
        sa.Index("agentcloud_jobs_tenant_idx", "tenant_id", "status"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    agent_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    parent_session_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    task: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, default="queued")
    payload: Mapped[dict] = mapped_column(JSONVariant, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class Usage(Base):
    """Per (tenant, agent, day) token + cost meter (design doc §6 metering)."""

    __tablename__ = "agentcloud_usage"

    tenant_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    agent_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    day: Mapped[date] = mapped_column(sa.Date, primary_key=True)
    input_tokens: Mapped[int] = mapped_column(sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(sa.Numeric(12, 6), nullable=False, default=0)
    requests: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
