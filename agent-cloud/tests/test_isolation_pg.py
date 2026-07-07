"""Sprint B1 — systematic RLS attack sweep over EVERY agentcloud_* table
(TENANCY.md §5, B9–B10). Extends the A2/A6 pattern of test_rls_pg.py from a
hand-picked table list to `migrations._RLS_TABLES` itself, so a future
table added to RLS is automatically covered — and B10 fails the suite if a
table has no seeded fixture row (no silently-green-but-empty sweep).

Skipped unless AGENTCLOUD_TEST_PG_DSN is set (non-superuser role — a
superuser bypasses RLS and these tests would fail spuriously).
"""

import os
import uuid

import pytest

from app.migrations import _RLS_TABLES

PG_DSN = os.environ.get("AGENTCLOUD_TEST_PG_DSN")

pytestmark = pytest.mark.skipif(
    not PG_DSN, reason="AGENTCLOUD_TEST_PG_DSN not set (needs Postgres)"
)

TENANT_A = "smoke-b1-victim"
TENANT_B = "smoke-b1-attacker"

_SESSION_ID = uuid.uuid4()

# One INSERT per RLS table, parameterized only by :t (tenant). B10 asserts
# this map covers _RLS_TABLES exactly — adding an RLS table without a seed
# here fails the suite.
SEED_SQL: dict[str, str] = {
    "agentcloud_tenants": "INSERT INTO agentcloud_tenants (tenant_id) VALUES (:t) ON CONFLICT DO NOTHING",
    "agentcloud_agents": (
        "INSERT INTO agentcloud_agents (tenant_id, agent_id, system_prompt, model) "
        "VALUES (:t, 'personal', 'x', 'claude-haiku-4-5') ON CONFLICT DO NOTHING"
    ),
    "agentcloud_sessions": (
        "INSERT INTO agentcloud_sessions (session_id, tenant_id, agent_id) "
        f"VALUES ('{_SESSION_ID}'::uuid, :t, 'personal') ON CONFLICT DO NOTHING"
    ),
    "agentcloud_messages": (
        "INSERT INTO agentcloud_messages (session_id, tenant_id, role, content) "
        f"VALUES ('{_SESSION_ID}'::uuid, :t, 'user', '\"secret\"'::jsonb)"
    ),
    "agentcloud_usage": (
        "INSERT INTO agentcloud_usage (tenant_id, agent_id, day, input_tokens) "
        "VALUES (:t, 'personal', CURRENT_DATE, 1) ON CONFLICT DO NOTHING"
    ),
    "agentcloud_memory": (
        "INSERT INTO agentcloud_memory (tenant_id, agent_id, kind, content) "
        "VALUES (:t, 'personal', 'fact', 'secret memory')"
    ),
    "agentcloud_events": (
        "INSERT INTO agentcloud_events (tenant_id, agent_id, session_id, type, payload) "
        f"VALUES (:t, 'personal', '{_SESSION_ID}'::uuid, 'turn.completed', '{{}}'::jsonb)"
    ),
    "agentcloud_jobs": (
        "INSERT INTO agentcloud_jobs (tenant_id, agent_id, task, status) "
        "VALUES (:t, 'personal', 'secret task', 'queued')"
    ),
    "agentcloud_schedules": (
        "INSERT INTO agentcloud_schedules (tenant_id, agent_id, name, kind, cron_expr) "
        "VALUES (:t, 'personal', 'secret schedule', 'cron', '0 9 * * *')"
    ),
    "agentcloud_proposals": (
        "INSERT INTO agentcloud_proposals (tenant_id, agent_id, tool_name, action, "
        "args, idempotency_key, quill_approval_id, status) "
        "VALUES (:t, 'personal', 'quill_project_update', 'project_update', "
        "'{}'::jsonb, 'sha256:' || :t, 'appr-b1', 'pending') ON CONFLICT DO NOTHING"
    ),
}


# Forged INSERTs: rows *claiming* tenant A (unique keys, valid FKs — RI
# checks bypass RLS, so the only thing that can reject these is the policy
# WITH CHECK) executed under tenant B's GUC. No ON CONFLICT clauses — a
# conflict short-circuit would skip the WITH CHECK evaluation.
FORGE_SQL: dict[str, str] = {
    "agentcloud_tenants": "INSERT INTO agentcloud_tenants (tenant_id) VALUES (:t || '-forged')",
    "agentcloud_agents": (
        "INSERT INTO agentcloud_agents (tenant_id, agent_id, system_prompt, model) "
        "VALUES (:t, 'forged-agent', 'x', 'claude-haiku-4-5')"
    ),
    "agentcloud_sessions": (
        "INSERT INTO agentcloud_sessions (session_id, tenant_id, agent_id) "
        f"VALUES ('{uuid.uuid4()}'::uuid, :t, 'personal')"
    ),
    "agentcloud_messages": (
        "INSERT INTO agentcloud_messages (session_id, tenant_id, role, content) "
        f"VALUES ('{_SESSION_ID}'::uuid, :t, 'user', '\"forged\"'::jsonb)"
    ),
    "agentcloud_usage": (
        "INSERT INTO agentcloud_usage (tenant_id, agent_id, day, input_tokens) "
        "VALUES (:t, 'personal', CURRENT_DATE - 1, 1)"
    ),
    "agentcloud_memory": (
        "INSERT INTO agentcloud_memory (tenant_id, agent_id, kind, content) "
        "VALUES (:t, 'personal', 'fact', 'forged memory')"
    ),
    "agentcloud_events": (
        "INSERT INTO agentcloud_events (tenant_id, agent_id, type, payload) "
        "VALUES (:t, 'personal', 'turn.completed', '{}'::jsonb)"
    ),
    "agentcloud_jobs": (
        "INSERT INTO agentcloud_jobs (tenant_id, agent_id, task, status) "
        "VALUES (:t, 'personal', 'forged task', 'queued')"
    ),
    "agentcloud_schedules": (
        "INSERT INTO agentcloud_schedules (tenant_id, agent_id, name, kind, cron_expr) "
        "VALUES (:t, 'personal', 'forged schedule', 'cron', '0 9 * * *')"
    ),
    "agentcloud_proposals": (
        "INSERT INTO agentcloud_proposals (tenant_id, agent_id, tool_name, action, "
        "args, idempotency_key, quill_approval_id, status) "
        "VALUES (:t, 'personal', 'quill_project_update', 'project_update', "
        "'{}'::jsonb, 'sha256:forged-' || :t, 'appr-b1-forged', 'pending')"
    ),
}


@pytest.fixture
async def pg_engine():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db import normalize_dsn
    from app.migrations import run_migrations

    engine = create_async_engine(normalize_dsn(PG_DSN))
    await run_migrations(engine)
    # seed tenant A (idempotent where keyed; extra rows are cleaned below)
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT_A}
        )
        for table in _RLS_TABLES:
            sql = SEED_SQL.get(table)
            if sql:
                await conn.execute(text(sql), {"t": TENANT_A})
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.admin', 'on', true)"))
        for t in reversed(_RLS_TABLES):
            await conn.execute(
                text(f"DELETE FROM {t} WHERE tenant_id LIKE 'smoke-b1-%'")
            )
        await conn.execute(
            text(
                "DELETE FROM agentcloud_tenants WHERE tenant_id LIKE 'smoke-b1-%'"
            )
        )
    await engine.dispose()


def test_seed_catalog_covers_every_rls_table():
    """B10 — a table added to _RLS_TABLES without a seed row here must fail."""
    assert set(SEED_SQL) == set(_RLS_TABLES)
    assert set(FORGE_SQL) == set(_RLS_TABLES)


@pytest.mark.parametrize("table", _RLS_TABLES)
async def test_seeded_row_visible_to_owner(pg_engine, table):
    """Guard against a green-but-empty sweep: every table really has a row."""
    from sqlalchemy import text

    async with pg_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT_A}
        )
        n = (
            await conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),
                {"t": TENANT_A},
            )
        ).scalar_one()
        assert n >= 1, f"{table}: fixture row missing — sweep would be vacuous"


@pytest.mark.parametrize("table", _RLS_TABLES)
async def test_wrong_tenant_guc_sees_zero_rows(pg_engine, table):
    from sqlalchemy import text

    async with pg_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT_B}
        )
        n = (
            await conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),
                {"t": TENANT_A},
            )
        ).scalar_one()
        assert n == 0, f"{table}: attacker GUC must not see victim rows"


@pytest.mark.parametrize("table", _RLS_TABLES)
async def test_absent_guc_sees_zero_rows(pg_engine, table):
    from sqlalchemy import text

    async with pg_engine.begin() as conn:
        n = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
        assert n == 0, f"{table}: missing GUC must see zero rows"


@pytest.mark.parametrize("table", _RLS_TABLES)
async def test_forged_insert_with_mismatched_guc_rejected(pg_engine, table):
    """WITH CHECK belt: writing a row claiming tenant A while the transaction
    GUC says tenant B must be rejected on every table — and rejected by the
    RLS policy specifically, not some incidental constraint."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    with pytest.raises((DBAPIError, ProgrammingError)) as excinfo:
        async with pg_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT_B}
            )
            await conn.execute(text(FORGE_SQL[table]), {"t": TENANT_A})
    assert "row-level security" in str(excinfo.value), (
        f"{table}: forge must be rejected by the RLS policy, got: {excinfo.value}"
    )
