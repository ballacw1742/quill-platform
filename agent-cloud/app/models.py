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
    # B2 (LIMITS.md §1): NULL = config default (TENANT_BUDGET_DEFAULT_USD for
    # user-* tenants, ORG_TENANT_BUDGET_USD otherwise); non-NULL = override.
    budget_monthly_usd: Mapped[float | None] = mapped_column(
        sa.Numeric(10, 2), nullable=True, default=None
    )
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
    # Phase 5 (AUTHORING_MATURITY.md §1.1) — monotonic version, +1 per mutating
    # update/rollback. Additive; existing rows default to 1.
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    # Phase 5 (AUTHORING_MATURITY.md §2.5) — tenant-scoped publish/share flag.
    published: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


class AgentVersion(Base):
    """Immutable snapshot of a superseded agent definition (Phase 5,
    AUTHORING_MATURITY.md §1.2). Written on every mutating update/rollback:
    the PRIOR live state is frozen here before the new state is applied.
    Insert-only; never mutated, never hard-deleted (audit/history).

    Tenant-scoped + RLS'd like every agentcloud_* table. The snapshot for
    version N-1 carries the forward metadata (change_action/changed_fields/
    rolled_back_from) describing the transition N-1 -> N, so the live head
    (version N) can reconstruct its own metadata (AUTHORING_MATURITY.md §5).
    """

    __tablename__ = "agentcloud_agent_versions"
    __table_args__ = (
        sa.Index(
            "agentcloud_agent_versions_tenant_idx",
            "tenant_id",
            "agent_id",
            "version",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_id",
            "version",
            name="agentcloud_agent_versions_uq",
        ),
    )

    version_row_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    agent_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    system_prompt: Mapped[str] = mapped_column(sa.Text, nullable=False)
    model: Mapped[str] = mapped_column(sa.Text, nullable=False)
    tools: Mapped[list] = mapped_column(JSONVariant, nullable=False, default=list)
    memory_policy: Mapped[str] = mapped_column(sa.Text, nullable=False, default="off")
    budget_monthly_usd: Mapped[float] = mapped_column(
        sa.Numeric(10, 2), nullable=False, default=20.0
    )
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    # created | updated | rolledback — what produced this snapshot's SUCCESSOR.
    change_action: Mapped[str] = mapped_column(sa.Text, nullable=False)
    changed_fields: Mapped[list] = mapped_column(
        JSONVariant, nullable=False, default=list
    )
    rolled_back_from: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
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


class Schedule(Base):
    """Per-tenant cron/reminder schedule (A4; design doc §2 "Cloud Scheduler
    (cron/reminders per tenant)"). kind: 'at' (one-shot) | 'cron' (recurring).
    next_run_at is always stored in UTC; tz math happens in app/scheduler.py.
    """

    __tablename__ = "agentcloud_schedules"
    __table_args__ = (
        sa.Index("agentcloud_schedules_due_idx", "enabled", "next_run_at"),
        sa.Index("agentcloud_schedules_tenant_idx", "tenant_id", "agent_id"),
    )

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    agent_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False)  # at | cron
    cron_expr: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    timezone: Mapped[str] = mapped_column(sa.Text, nullable=False, default="UTC")
    run_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    # {"message": "..."} — the agent-turn message (reminder text / task)
    payload: Mapped[dict] = mapped_column(JSONVariant, nullable=False, default=dict)
    # optional target session: the fired job wakes it on completion (EVENTS.md)
    session_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    delete_after_run: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


class Proposal(Base):
    """Agent-proposed Quill write pending human approval (APPROVALS.md).

    status: pending | executed | declined | failed | expired. The terminal
    transition is a conditional UPDATE (WHERE status='pending') so the
    notify and reconcile paths can race without double-finalizing.
    """

    __tablename__ = "agentcloud_proposals"
    __table_args__ = (
        sa.Index("agentcloud_proposals_tenant_idx", "tenant_id", "status"),
    )

    proposal_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    agent_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    tool_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    action: Mapped[str] = mapped_column(sa.Text, nullable=False)
    args: Mapped[dict] = mapped_column(JSONVariant, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    quill_approval_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, default="pending")
    result: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class ChannelLink(Base):
    """External channel identity ↔ (tenant, agent) binding (Phase D,
    CHANNELS.md §3). A pairing code is minted by an authenticated web user
    (status='pending'); redeeming it from the bot binds the platform identity
    (status='linked'). status: pending | linked | revoked.

    Routing (inbound webhook) is a lookup on (platform, platform_chat_id,
    status='linked'). session_id is the per-link conversation session, set
    lazily on the first inbound message so a channel conversation has
    continuity across turns.
    """

    __tablename__ = "agentcloud_channel_links"
    __table_args__ = (
        sa.Index("agentcloud_channel_links_tenant_idx", "tenant_id", "status"),
    )

    link_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    agent_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    platform: Mapped[str] = mapped_column(sa.Text, nullable=False)  # telegram | googlechat
    platform_user_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    platform_chat_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, default="pending")
    pairing_code: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    code_expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    linked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
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


class RateLimit(Base):
    """Per (tenant, bucket, minute-window) fixed-window request counter
    (B2, LIMITS.md §3). Multi-instance-safe because the counter lives in
    the shared Postgres; one upsert-increment per request."""

    __tablename__ = "agentcloud_rate_limits"

    tenant_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    bucket: Mapped[str] = mapped_column(sa.Text, primary_key=True)  # chat | jobs
    window_start: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), primary_key=True
    )
    count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)


class TenantSecret(Base):
    """Per-tenant secret row — envelope-encrypted per SECRETS.md (B2).
    All access goes through app/secrets.py; values never leave that module
    except on the sanctioned get_secret() read path."""

    __tablename__ = "agentcloud_tenant_secrets"

    tenant_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    name: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    backend: Mapped[str] = mapped_column(sa.Text, nullable=False)  # plaintext-dev | kms
    kms_key_ref: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    dek_wrapped: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    nonce: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    ciphertext: Mapped[bytes] = mapped_column(sa.LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    rotated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
