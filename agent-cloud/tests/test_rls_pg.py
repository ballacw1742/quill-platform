"""Postgres RLS integration tests — DB-level second belt.

Skipped unless AGENTCLOUD_TEST_PG_DSN is set (needs a real Postgres; the
tables + policies are created by app.migrations). In prod the same proof is
produced by `python -m app.admin rls-probe` running as a Cloud Run job with
the app's DATABASE_URL (see agent-cloud/README.md — A1 gate evidence).
"""

import os
import uuid

import pytest

PG_DSN = os.environ.get("AGENTCLOUD_TEST_PG_DSN")

pytestmark = pytest.mark.skipif(
    not PG_DSN, reason="AGENTCLOUD_TEST_PG_DSN not set (needs Postgres)"
)

TENANT_A = "smoke-rls-a"
TENANT_B = "smoke-rls-b"


@pytest.fixture
async def pg_engine():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db import normalize_dsn
    from app.migrations import run_migrations

    engine = create_async_engine(normalize_dsn(PG_DSN))
    await run_migrations(engine)
    yield engine
    # cleanup smoke rows
    async with engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.admin', 'on', true)"))
        for t in (
            "agentcloud_schedules",
            "agentcloud_events",
            "agentcloud_jobs",
            "agentcloud_messages",
            "agentcloud_sessions",
            "agentcloud_usage",
            "agentcloud_agents",
            "agentcloud_tenants",
        ):
            await conn.execute(
                text(f"DELETE FROM {t} WHERE tenant_id LIKE 'smoke-rls-%'")
            )
    await engine.dispose()


async def _seed(engine, tenant: str) -> uuid.UUID:
    from sqlalchemy import text

    sid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant}
        )
        await conn.execute(
            text("INSERT INTO agentcloud_tenants (tenant_id) VALUES (:t) ON CONFLICT DO NOTHING"),
            {"t": tenant},
        )
        await conn.execute(
            text(
                "INSERT INTO agentcloud_agents (tenant_id, agent_id, system_prompt, model) "
                "VALUES (:t, 'personal', 'x', 'claude-haiku-4-5') ON CONFLICT DO NOTHING"
            ),
            {"t": tenant},
        )
        await conn.execute(
            text(
                "INSERT INTO agentcloud_sessions (session_id, tenant_id, agent_id) "
                "VALUES (:s, :t, 'personal')"
            ),
            {"s": sid, "t": tenant},
        )
        await conn.execute(
            text(
                "INSERT INTO agentcloud_messages (session_id, tenant_id, role, content) "
                "VALUES (:s, :t, 'user', '\"secret\"'::jsonb)"
            ),
            {"s": sid, "t": tenant},
        )
        # A3 tables: one event + one job per tenant
        await conn.execute(
            text(
                "INSERT INTO agentcloud_events (tenant_id, agent_id, session_id, type, payload) "
                "VALUES (:t, 'personal', :s, 'turn.completed', '{}'::jsonb)"
            ),
            {"t": tenant, "s": sid},
        )
        await conn.execute(
            text(
                "INSERT INTO agentcloud_jobs (tenant_id, agent_id, task, status) "
                "VALUES (:t, 'personal', 'secret task', 'queued')"
            ),
            {"t": tenant},
        )
        # A4 table: one schedule per tenant
        await conn.execute(
            text(
                "INSERT INTO agentcloud_schedules "
                "(tenant_id, agent_id, name, kind, cron_expr) "
                "VALUES (:t, 'personal', 'secret schedule', 'cron', '0 9 * * *')"
            ),
            {"t": tenant},
        )
    return sid


async def test_rls_wrong_tenant_guc_sees_zero_rows(pg_engine):
    from sqlalchemy import text

    await _seed(pg_engine, TENANT_A)
    async with pg_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT_B}
        )
        for table in (
            "agentcloud_sessions",
            "agentcloud_messages",
            "agentcloud_tenants",
            "agentcloud_events",
            "agentcloud_jobs",
            "agentcloud_schedules",
        ):
            n = (
                await conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),
                    {"t": TENANT_A},
                )
            ).scalar_one()
            assert n == 0, f"{table}: tenant B GUC must not see tenant A rows"


async def test_rls_no_guc_sees_zero_rows(pg_engine):
    from sqlalchemy import text

    await _seed(pg_engine, TENANT_A)
    async with pg_engine.begin() as conn:
        n = (
            await conn.execute(text("SELECT count(*) FROM agentcloud_messages"))
        ).scalar_one()
        assert n == 0


async def test_rls_correct_guc_sees_own_rows(pg_engine):
    from sqlalchemy import text

    await _seed(pg_engine, TENANT_A)
    async with pg_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT_A}
        )
        for table in (
            "agentcloud_sessions",
            "agentcloud_events",
            "agentcloud_jobs",
            "agentcloud_schedules",
        ):
            n = (
                await conn.execute(text(f"SELECT count(*) FROM {table}"))
            ).scalar_one()
            assert n >= 1, f"{table}: own-tenant GUC must see own rows"


async def test_rls_no_guc_sees_zero_a3_rows(pg_engine):
    from sqlalchemy import text

    await _seed(pg_engine, TENANT_A)
    async with pg_engine.begin() as conn:
        for table in ("agentcloud_events", "agentcloud_jobs", "agentcloud_schedules"):
            n = (
                await conn.execute(text(f"SELECT count(*) FROM {table}"))
            ).scalar_one()
            assert n == 0, f"{table}: no GUC must see zero rows"


async def test_rls_insert_wrong_tenant_rejected(pg_engine):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    await _seed(pg_engine, TENANT_A)
    with pytest.raises((DBAPIError, ProgrammingError)):
        async with pg_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT_B}
            )
            await conn.execute(
                text(
                    "INSERT INTO agentcloud_tenants (tenant_id) VALUES (:t)"
                ),
                {"t": TENANT_A + "-forged"},
            )
