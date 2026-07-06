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

log = logging.getLogger("agentcloud.migrations")

DDL_TABLES = """
CREATE TABLE IF NOT EXISTS agentcloud_tenants (
    tenant_id   TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS agentcloud_agents (
    tenant_id     TEXT NOT NULL REFERENCES agentcloud_tenants(tenant_id),
    agent_id      TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    model         TEXT NOT NULL,
    tools         JSONB NOT NULL DEFAULT '["get_time","quill_finance_summary"]',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, agent_id)
);
CREATE TABLE IF NOT EXISTS agentcloud_sessions (
    session_id  UUID PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, agent_id)
        REFERENCES agentcloud_agents(tenant_id, agent_id)
);
CREATE INDEX IF NOT EXISTS agentcloud_sessions_tenant_idx
    ON agentcloud_sessions (tenant_id, agent_id);
CREATE TABLE IF NOT EXISTS agentcloud_messages (
    message_id  BIGSERIAL PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES agentcloud_sessions(session_id),
    tenant_id   TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agentcloud_messages_session_idx
    ON agentcloud_messages (tenant_id, session_id, message_id);
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
);
"""

DDL_ADDITIVE = """
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS budget_monthly_usd NUMERIC(10,2) NOT NULL DEFAULT 20.00;
ALTER TABLE agentcloud_agents
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE;
"""

_RLS_TABLES = [
    "agentcloud_tenants",
    "agentcloud_agents",
    "agentcloud_sessions",
    "agentcloud_messages",
    "agentcloud_usage",
]


def _rls_ddl(table: str) -> str:
    return f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY {table}_tenant_isolation ON {table}
        USING (tenant_id = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE POLICY {table}_admin ON {table}
        USING (current_setting('app.admin', true) = 'on')
        WITH CHECK (current_setting('app.admin', true) = 'on');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""


async def run_migrations(engine: AsyncEngine) -> None:
    """Apply all DDL. Postgres only; sqlite (tests) uses ORM create_all."""
    if engine.dialect.name != "postgresql":
        from app.db import Base  # noqa: PLC0415
        import app.models  # noqa: F401, PLC0415  (register tables)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return

    async with engine.begin() as conn:
        await conn.execute(text(DDL_TABLES))
        await conn.execute(text(DDL_ADDITIVE))
        for table in _RLS_TABLES:
            await conn.execute(text(_rls_ddl(table)))
    log.info("agentcloud migrations applied (tables + additive columns + RLS)")
