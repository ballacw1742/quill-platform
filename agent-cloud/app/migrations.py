"""Additive, idempotent DDL for the agentcloud_* tables (own-DDL pattern,
same as dispatch-worker / the P0 spike — decoupled from API Alembic).

Everything here is safe to run on every startup:
  - CREATE TABLE IF NOT EXISTS (original spike tables + new agentcloud_usage)
  - ALTER TABLE ... ADD COLUMN IF NOT EXISTS (A1 additive columns)
  - ENABLE/FORCE ROW LEVEL SECURITY + tenant policy + admin policy
    (CREATE POLICY wrapped in duplicate_object-tolerant DO blocks)

RLS design:
  - tenant policy: rows visible iff tenant_id = current_setting('app.tenant_id', true)
  - admin policy (OR'd): visible iff current_setting('app.admin', true) = 'on'
    — used only by app/admin.py maintenance CLI, never on the request path.
  - FORCE means the policy applies to the table owner too (the app role
    owns these tables), so raw SQL as the app role with a wrong/missing
    tenant GUC returns zero rows. Verified by `python -m app.admin rls-probe`.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import get_settings

log = logging.getLogger("agentcloud.migrations")

# NOTE: asyncpg cannot prepare multi-statement strings — every entry below
# must be exactly one SQL statement (DO $$ ... $$ blocks count as one).
DDL_TABLES = [
    """
CREATE TABLE IF NOT EXISTS agentcloud_tenants (
    tenant_id   TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """
CREATE TABLE IF NOT EXISTS agentcloud_agents (
    tenant_id     TEXT NOT NULL REFERENCES agentcloud_tenants(tenant_id),
    agent_id      TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    model         TEXT NOT NULL,
    tools         JSONB NOT NULL DEFAULT '["get_time","quill_finance_summary"]',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, agent_id)
)""",
    """
CREATE TABLE IF NOT EXISTS agentcloud_sessions (
    session_id  UUID PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, agent_id)
        REFERENCES agentcloud_agents(tenant_id, agent_id)
)""",
    """
CREATE INDEX IF NOT EXISTS agentcloud_sessions_tenant_idx
    ON agentcloud_sessions (tenant_id, agent_id)""",
    """
CREATE TABLE IF NOT EXISTS agentcloud_messages (
    message_id  BIGSERIAL PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES agentcloud_sessions(session_id),
    tenant_id   TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """
CREATE INDEX IF NOT EXISTS agentcloud_messages_session_idx
    ON agentcloud_messages (tenant_id, session_id, message_id)""",
    """
CREATE TABLE IF NOT EXISTS agentcloud_usage (
    tenant_id     TEXT NOT NULL,
    agent_id      TEXT NOT NULL,
    day           DATE NOT NULL,
    input_tokens  BIGINT NOT NULL DEFAULT 0,
    output_tokens BIGINT NOT NULL DEFAULT 0,
    cost_usd      NUMERIC(12,6) NOT NULL DEFAULT 0,
    requests      INTEGER NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, agent_id, day)
)""",
]

DDL_ADDITIVE = [
    """
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS budget_monthly_usd NUMERIC(10,2) NOT NULL DEFAULT 20.00""",
    """
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE""",
    # A2: memory_policy — off | tools_only | auto_recall (design doc §3.3
    # agent-definitions-as-data; enforced in orchestrator, default safe).
    """
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS memory_policy TEXT NOT NULL DEFAULT 'off'""",
    # ADK task-agents + sharing + governance (ADK_AGENTS_DESIGN.md §1).
    # All additive with safe defaults — no reorder/rename of existing cols.
    """
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS agent_kind TEXT NOT NULL DEFAULT 'assistant'""",
    """
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS runtime TEXT NOT NULL DEFAULT 'claude'""",
    """
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS owner_user_id TEXT""",
    """
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'""",
    """
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS approval_state TEXT NOT NULL DEFAULT 'draft'""",
    """
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS adk_config JSONB""",
    # Phase 1 (GAP §9.4): risk-graded lane. trust_tier hint on the operating
    # layer; canonical tier is api-side AgentRegistration.trust_tier. Default
    # strictest so a new agent never auto-executes until promoted.
    """
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS trust_tier TEXT NOT NULL DEFAULT 'tier-0-mandatory'""",
    # Hybrid Sensitivity Router (scaled-down §8): static per-agent model lane.
    # local (fail-safe default, on-prem inference) | frontier (Claude API for
    # non-sensitive agents). Default is the safe lane so a new agent keeps
    # data on-prem until explicitly promoted.
    """
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS model_lane TEXT NOT NULL DEFAULT 'local'""",
]

# Phase 5: agent authoring maturity — versioning/diff/rollback/publish
# (AUTHORING_MATURITY.md). One statement each (asyncpg constraint), additive +
# idempotent. Two columns on agentcloud_agents (version, published) + a new
# immutable-snapshot table with a unique index per (tenant, agent, version).
DDL_P5 = [
    """
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1""",
    """
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS published BOOLEAN NOT NULL DEFAULT FALSE""",
    """
CREATE TABLE IF NOT EXISTS agentcloud_agent_versions (
    version_row_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          TEXT NOT NULL,
    agent_id           TEXT NOT NULL,
    version            INTEGER NOT NULL,
    system_prompt      TEXT NOT NULL,
    model              TEXT NOT NULL,
    tools              JSONB NOT NULL DEFAULT '[]',
    memory_policy      TEXT NOT NULL DEFAULT 'off',
    budget_monthly_usd NUMERIC(10,2) NOT NULL DEFAULT 20.00,
    enabled            BOOLEAN NOT NULL DEFAULT TRUE,
    change_action      TEXT NOT NULL,
    changed_fields     JSONB NOT NULL DEFAULT '[]',
    rolled_back_from   INTEGER,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """
CREATE INDEX IF NOT EXISTS agentcloud_agent_versions_tenant_idx
    ON agentcloud_agent_versions (tenant_id, agent_id, version)""",
    """
CREATE UNIQUE INDEX IF NOT EXISTS agentcloud_agent_versions_uq
    ON agentcloud_agent_versions (tenant_id, agent_id, version)""",
]


def _memory_ddl(dim: int) -> list[str]:
    """A2 memory table. Every entry is one statement (asyncpg constraint).

    pgvector: `CREATE EXTENSION vector` may need privileges the app role
    lacks; the DO block degrades cleanly (NOTICE, no failure). The embedding
    column + ANN index are only added when the extension is present, so the
    table (and text-search fallback) works without pgvector. Cloud SQL
    Postgres ships pgvector, so prod gets the vector path.
    """
    dim = int(dim)
    return [
        """DO $$ BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION WHEN insufficient_privilege OR undefined_file THEN
    RAISE NOTICE 'pgvector extension unavailable (%) — memory falls back to text search', SQLERRM;
END $$""",
        """
CREATE TABLE IF NOT EXISTS agentcloud_memory (
    memory_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     TEXT NOT NULL,
    agent_id      TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'fact',
    content       TEXT NOT NULL,
    metadata      JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_accessed TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, agent_id)
        REFERENCES agentcloud_agents(tenant_id, agent_id)
)""",
        """
CREATE INDEX IF NOT EXISTS agentcloud_memory_tenant_idx
    ON agentcloud_memory (tenant_id, agent_id, kind)""",
        f"""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        ALTER TABLE agentcloud_memory
            ADD COLUMN IF NOT EXISTS embedding vector({dim});
    END IF;
END $$""",
        """DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        CREATE INDEX IF NOT EXISTS agentcloud_memory_embedding_idx
            ON agentcloud_memory USING hnsw (embedding vector_cosine_ops);
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'hnsw index unavailable (%) — sequential vector scan', SQLERRM;
END $$""",
    ]

# A3: durable events + sub-agent jobs (EVENTS.md). One statement each
# (asyncpg constraint), additive + idempotent.
DDL_A3 = [
    """
CREATE TABLE IF NOT EXISTS agentcloud_events (
    event_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   TEXT NOT NULL,
    agent_id    TEXT NOT NULL DEFAULT '',
    session_id  UUID,
    type        TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}',
    attempt     INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """
CREATE INDEX IF NOT EXISTS agentcloud_events_tenant_idx
    ON agentcloud_events (tenant_id, created_at)""",
    """
CREATE TABLE IF NOT EXISTS agentcloud_jobs (
    job_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         TEXT NOT NULL,
    agent_id          TEXT NOT NULL,
    parent_session_id UUID,
    session_id        UUID,
    task              TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'queued',
    payload           JSONB NOT NULL DEFAULT '{}',
    result            JSONB,
    error             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ
)""",
    """
CREATE INDEX IF NOT EXISTS agentcloud_jobs_tenant_idx
    ON agentcloud_jobs (tenant_id, status)""",
]

# A4: per-tenant schedules (cron/reminders). One statement each (asyncpg
# constraint), additive + idempotent.
DDL_A4 = [
    """
CREATE TABLE IF NOT EXISTS agentcloud_schedules (
    schedule_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        TEXT NOT NULL,
    agent_id         TEXT NOT NULL,
    name             TEXT NOT NULL,
    kind             TEXT NOT NULL,
    cron_expr        TEXT,
    timezone         TEXT NOT NULL DEFAULT 'UTC',
    run_at           TIMESTAMPTZ,
    payload          JSONB NOT NULL DEFAULT '{}',
    session_id       UUID,
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    delete_after_run BOOLEAN NOT NULL DEFAULT FALSE,
    next_run_at      TIMESTAMPTZ,
    last_run_at      TIMESTAMPTZ,
    last_status      TEXT,
    last_job_id      UUID,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """
CREATE INDEX IF NOT EXISTS agentcloud_schedules_due_idx
    ON agentcloud_schedules (enabled, next_run_at)""",
    """
CREATE INDEX IF NOT EXISTS agentcloud_schedules_tenant_idx
    ON agentcloud_schedules (tenant_id, agent_id)""",
]

# A6: agent-proposed writes → Quill HITL approvals (APPROVALS.md). One
# statement each (asyncpg constraint), additive + idempotent. The partial
# unique index is the queue-time idempotency belt: one *pending* proposal
# per (tenant, args-hash).
DDL_A6 = [
    """
CREATE TABLE IF NOT EXISTS agentcloud_proposals (
    proposal_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         TEXT NOT NULL,
    agent_id          TEXT NOT NULL,
    session_id        UUID,
    tool_name         TEXT NOT NULL,
    action            TEXT NOT NULL,
    args              JSONB NOT NULL DEFAULT '{}',
    idempotency_key   TEXT NOT NULL,
    quill_approval_id TEXT,
    status            TEXT NOT NULL DEFAULT 'pending',
    result            JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at       TIMESTAMPTZ
)""",
    """
CREATE INDEX IF NOT EXISTS agentcloud_proposals_tenant_idx
    ON agentcloud_proposals (tenant_id, status)""",
    """
CREATE UNIQUE INDEX IF NOT EXISTS agentcloud_proposals_idem_idx
    ON agentcloud_proposals (tenant_id, idempotency_key) WHERE status = 'pending'""",
]

# B2: tenant budgets + rate limits + per-tenant secrets (LIMITS.md,
# SECRETS.md). One statement each (asyncpg constraint), additive +
# idempotent.
DDL_B2 = [
    """
ALTER TABLE agentcloud_tenants
    ADD COLUMN IF NOT EXISTS budget_monthly_usd NUMERIC(10,2)""",
    """
CREATE TABLE IF NOT EXISTS agentcloud_rate_limits (
    tenant_id    TEXT NOT NULL,
    bucket       TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    count        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, bucket, window_start)
)""",
    """
CREATE TABLE IF NOT EXISTS agentcloud_tenant_secrets (
    tenant_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    backend     TEXT NOT NULL,
    kms_key_ref TEXT,
    dek_wrapped BYTEA,
    nonce       BYTEA,
    ciphertext  BYTEA NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    rotated_at  TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, name)
)""",
]

# D: external channel adapters (Telegram + Google Chat) + pairing links
# (CHANNELS.md §3). One statement each (asyncpg constraint), additive +
# idempotent. Two partial unique indexes are the routing/pairing belts:
#   - one pending code resolves to at most one row,
#   - at most one live link per (platform, chat/space).
DDL_D = [
    """
CREATE TABLE IF NOT EXISTS agentcloud_channel_links (
    link_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        TEXT NOT NULL,
    agent_id         TEXT NOT NULL,
    platform         TEXT NOT NULL,
    platform_user_id TEXT,
    platform_chat_id TEXT,
    display_name     TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',
    pairing_code     TEXT,
    code_expires_at  TIMESTAMPTZ,
    session_id       UUID,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    linked_at        TIMESTAMPTZ,
    revoked_at       TIMESTAMPTZ
)""",
    """
CREATE INDEX IF NOT EXISTS agentcloud_channel_links_tenant_idx
    ON agentcloud_channel_links (tenant_id, status)""",
    """
CREATE UNIQUE INDEX IF NOT EXISTS agentcloud_channel_links_code_idx
    ON agentcloud_channel_links (platform, pairing_code) WHERE status = 'pending'""",
    """
CREATE UNIQUE INDEX IF NOT EXISTS agentcloud_channel_links_route_idx
    ON agentcloud_channel_links (platform, platform_chat_id) WHERE status = 'linked'""",
]

# ADK: workflow assignments (ADK_AGENTS_DESIGN.md §4). Governed data overlay
# of the base chains. One statement each (asyncpg constraint), additive +
# idempotent. A partial unique index enforces at most one *approved*
# assignment per (workflow_id, stage_key) — the overlay is deterministic.
DDL_ADK = [
    """
CREATE TABLE IF NOT EXISTS agentcloud_workflow_assignments (
    assignment_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id          TEXT NOT NULL,
    stage_key            TEXT NOT NULL,
    agent_id             TEXT NOT NULL,
    owner_tenant_id      TEXT NOT NULL,
    suggested_by_user_id TEXT NOT NULL,
    state                TEXT NOT NULL DEFAULT 'suggested',
    approval_item_id     TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by          TEXT,
    approved_at          TIMESTAMPTZ
)""",
    """
CREATE INDEX IF NOT EXISTS agentcloud_workflow_assignments_tenant_idx
    ON agentcloud_workflow_assignments (owner_tenant_id, state)""",
    """
CREATE INDEX IF NOT EXISTS agentcloud_workflow_assignments_stage_idx
    ON agentcloud_workflow_assignments (workflow_id, stage_key, state)""",
    """
CREATE UNIQUE INDEX IF NOT EXISTS agentcloud_workflow_assignments_approved_idx
    ON agentcloud_workflow_assignments (workflow_id, stage_key)
    WHERE state = 'approved'""",
]

# The workflow-assignments table keys its tenant column `owner_tenant_id`
# (not `tenant_id`), so it gets a bespoke RLS policy instead of the shared
# _RLS_TABLES loop below.
DDL_ADK_RLS = [
    "ALTER TABLE agentcloud_workflow_assignments ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE agentcloud_workflow_assignments FORCE ROW LEVEL SECURITY",
    """DO $$ BEGIN
    CREATE POLICY agentcloud_workflow_assignments_tenant_isolation
        ON agentcloud_workflow_assignments
        USING (owner_tenant_id = current_setting('app.tenant_id', true))
        WITH CHECK (owner_tenant_id = current_setting('app.tenant_id', true));
EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
    CREATE POLICY agentcloud_workflow_assignments_admin
        ON agentcloud_workflow_assignments
        USING (current_setting('app.admin', true) = 'on')
        WITH CHECK (current_setting('app.admin', true) = 'on');
EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
]

_RLS_TABLES = [
    "agentcloud_tenants",
    "agentcloud_agents",
    "agentcloud_sessions",
    "agentcloud_messages",
    "agentcloud_usage",
    "agentcloud_memory",
    "agentcloud_events",
    "agentcloud_jobs",
    "agentcloud_schedules",
    "agentcloud_proposals",
    "agentcloud_rate_limits",
    "agentcloud_tenant_secrets",
    "agentcloud_channel_links",
    "agentcloud_agent_versions",
]


def _rls_ddl(table: str) -> list[str]:
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"""DO $$ BEGIN
    CREATE POLICY {table}_tenant_isolation ON {table}
        USING (tenant_id = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
        f"""DO $$ BEGIN
    CREATE POLICY {table}_admin ON {table}
        USING (current_setting('app.admin', true) = 'on')
        WITH CHECK (current_setting('app.admin', true) = 'on');
EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    ]


async def run_migrations(engine: AsyncEngine) -> None:
    """Apply all DDL. Postgres only; sqlite (tests) uses ORM create_all."""
    if engine.dialect.name != "postgresql":
        from app.db import Base  # noqa: PLC0415
        import app.models  # noqa: F401, PLC0415  (register tables)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return

    statements: list[str] = [
        *DDL_TABLES,
        *DDL_ADDITIVE,
        *_memory_ddl(get_settings().EMBEDDING_DIM),
        *DDL_A3,
        *DDL_A4,
        *DDL_A6,
        *DDL_B2,
        *DDL_D,
        *DDL_ADK,
        *DDL_P5,
    ]
    for table in _RLS_TABLES:
        statements.extend(_rls_ddl(table))
    statements.extend(DDL_ADK_RLS)
    async with engine.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))
    log.info(
        "agentcloud migrations applied (tables + additive columns + memory + events + jobs + schedules + proposals + rate-limits + tenant-secrets + channel-links + agent-versions + RLS)"
    )
