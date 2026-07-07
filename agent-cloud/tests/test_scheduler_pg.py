"""Postgres-gated scheduler tests: RLS on agentcloud_schedules, migration
run-twice idempotency, FOR UPDATE SKIP LOCKED claim concurrency, and a full
tick→job pass against Postgres.

Skipped unless AGENTCLOUD_TEST_PG_DSN is set (same convention as
tests/test_rls_pg.py; the role must be a non-superuser or RLS is bypassed).
"""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

PG_DSN = os.environ.get("AGENTCLOUD_TEST_PG_DSN")

pytestmark = pytest.mark.skipif(
    not PG_DSN, reason="AGENTCLOUD_TEST_PG_DSN not set (needs Postgres)"
)

TENANT_A = "smoke-schedrls-a"
TENANT_B = "smoke-schedrls-b"

UTC = timezone.utc


@pytest.fixture
async def pg_engine():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db import normalize_dsn
    from app.migrations import run_migrations

    engine = create_async_engine(normalize_dsn(PG_DSN))
    await run_migrations(engine)
    # idempotency gate: running migrations twice must be safe
    await run_migrations(engine)
    yield engine
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
                text(f"DELETE FROM {t} WHERE tenant_id LIKE 'smoke-schedrls-%'")
            )
    await engine.dispose()


@pytest.fixture
async def pg_sessions(pg_engine, monkeypatch):
    """Point app.db's dynamically-resolved SessionLocal at the pg engine so
    tenant_session/admin_session (and everything built on them) run on
    Postgres for the duration of a test."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db as db_mod

    maker = async_sessionmaker(bind=pg_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(db_mod, "SessionLocal", maker)
    yield maker


async def _seed_schedule(engine, tenant: str, *, due: bool = True) -> uuid.UUID:
    from sqlalchemy import text

    sid = uuid.uuid4()
    when = datetime.now(UTC) + (timedelta(minutes=-5) if due else timedelta(hours=1))
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
                "INSERT INTO agentcloud_schedules "
                "(schedule_id, tenant_id, agent_id, name, kind, run_at, payload, next_run_at) "
                "VALUES (:s, :t, 'personal', 'secret schedule', 'at', :w, "
                "'{\"message\": \"secret reminder\"}'::jsonb, :w)"
            ),
            {"s": sid, "t": tenant, "w": when},
        )
    return sid


# --------------------------------------------------------------------------
# migration idempotency + RLS
# --------------------------------------------------------------------------

async def test_migrations_idempotent_and_schedules_table_complete(pg_engine):
    from sqlalchemy import text

    async with pg_engine.connect() as conn:
        cols = {
            r[0]
            for r in await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'agentcloud_schedules'"
                )
            )
        }
        expected = {
            "schedule_id", "tenant_id", "agent_id", "name", "kind", "cron_expr",
            "timezone", "run_at", "payload", "session_id", "enabled",
            "delete_after_run", "next_run_at", "last_run_at", "last_status",
            "last_job_id", "created_at", "updated_at",
        }
        assert expected <= cols
        policies = {
            r[0]
            for r in await conn.execute(
                text(
                    "SELECT policyname FROM pg_policies "
                    "WHERE tablename = 'agentcloud_schedules'"
                )
            )
        }
        assert "agentcloud_schedules_tenant_isolation" in policies
        assert "agentcloud_schedules_admin" in policies
        rls = (
            await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'agentcloud_schedules'"
                )
            )
        ).one()
        assert rls[0] is True and rls[1] is True  # ENABLE + FORCE


async def test_schedules_rls_isolation(pg_engine):
    from sqlalchemy import text

    await _seed_schedule(pg_engine, TENANT_A)
    # wrong tenant GUC ⇒ zero rows
    async with pg_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT_B}
        )
        n = (
            await conn.execute(
                text("SELECT count(*) FROM agentcloud_schedules WHERE tenant_id = :t"),
                {"t": TENANT_A},
            )
        ).scalar_one()
        assert n == 0
    # no GUC ⇒ zero rows
    async with pg_engine.begin() as conn:
        n = (
            await conn.execute(text("SELECT count(*) FROM agentcloud_schedules"))
        ).scalar_one()
        assert n == 0
    # correct GUC ⇒ own rows
    async with pg_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT_A}
        )
        n = (
            await conn.execute(text("SELECT count(*) FROM agentcloud_schedules"))
        ).scalar_one()
        assert n >= 1


async def test_schedules_rls_forged_insert_rejected(pg_engine):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    with pytest.raises((DBAPIError, ProgrammingError)):
        async with pg_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT_B}
            )
            await conn.execute(
                text(
                    "INSERT INTO agentcloud_schedules "
                    "(tenant_id, agent_id, name, kind) "
                    "VALUES (:t, 'personal', 'forged', 'at')"
                ),
                {"t": TENANT_A},
            )


# --------------------------------------------------------------------------
# claim concurrency (FOR UPDATE SKIP LOCKED)
# --------------------------------------------------------------------------

async def test_claim_skips_rows_locked_by_concurrent_instance(pg_engine, pg_sessions):
    """While one 'instance' holds FOR UPDATE locks on a subset of due rows,
    a concurrent claim must skip exactly those rows (SKIP LOCKED) — no
    double-claim, no blocking."""
    from sqlalchemy import text

    from app import scheduler as scheduler_mod
    from app.models import Schedule

    all_ids = {str(await _seed_schedule(pg_engine, TENANT_A)) for _ in range(6)}
    now = datetime.now(UTC)

    async with pg_sessions() as locker:
        async with locker.begin():
            await locker.execute(text("SELECT set_config('app.admin', 'on', true)"))
            locked_rows = (
                (
                    await locker.execute(
                        sa.select(Schedule.schedule_id)
                        .where(
                            Schedule.tenant_id == TENANT_A,
                            Schedule.next_run_at.is_not(None),
                        )
                        .order_by(Schedule.next_run_at)
                        .limit(3)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            locked_ids = {str(x) for x in locked_rows}
            assert len(locked_ids) == 3

            # concurrent claim on a separate connection, locks still held
            claimed = await scheduler_mod._claim_due(now)
            claimed_ids = {str(c["schedule_id"]) for c in claimed}
            assert claimed_ids.isdisjoint(locked_ids)
            assert claimed_ids == all_ids - locked_ids

    # locks released; the remaining rows are still claimable exactly once
    claimed2 = await scheduler_mod._claim_due(now)
    claimed2_ids = {str(c["schedule_id"]) for c in claimed2}
    assert claimed2_ids == locked_ids
    # everything claimed once; nothing left
    assert await scheduler_mod._claim_due(now) == []


async def test_parallel_claims_never_double_claim(pg_engine, pg_sessions, monkeypatch):
    from app import scheduler as scheduler_mod

    monkeypatch.setattr(
        scheduler_mod.get_settings(), "SCHEDULER_MAX_PER_TICK", 2
    )
    try:
        all_ids = {str(await _seed_schedule(pg_engine, TENANT_A)) for _ in range(6)}
        now = datetime.now(UTC)
        results = await asyncio.gather(
            *[scheduler_mod._claim_due(now) for _ in range(4)]
        )
    finally:
        monkeypatch.setattr(
            scheduler_mod.get_settings(), "SCHEDULER_MAX_PER_TICK", 25
        )
    seen: list[str] = []
    for batch in results:
        seen.extend(str(c["schedule_id"]) for c in batch)
    assert len(seen) == len(set(seen)), "a schedule was claimed twice"
    assert set(seen) <= all_ids


# --------------------------------------------------------------------------
# full tick → job on Postgres (RLS'd writes end-to-end)
# --------------------------------------------------------------------------

async def test_tick_fires_job_on_postgres(pg_engine, pg_sessions, monkeypatch):
    from app import jobs as jobs_mod
    from app import orchestrator as orch_mod
    from app import scheduler as scheduler_mod
    from tests.conftest import FakeProvider, text_response

    monkeypatch.setattr(
        orch_mod, "get_provider", lambda: FakeProvider([text_response("pg reminder")])
    )
    sid = await _seed_schedule(pg_engine, TENANT_A)
    res = await scheduler_mod.tick()
    assert res["claimed"] >= 1 and res["failed"] == 0

    after = await scheduler_mod.get_schedule(TENANT_A, sid)
    assert after["last_status"] == "fired"
    job_id = uuid.UUID(after["last_job_id"])
    for _ in range(150):
        await asyncio.sleep(0.02)
        job = await jobs_mod.get_job(TENANT_A, job_id)
        if job["status"] not in ("queued", "running"):
            break
    assert job["status"] == "ok"
    assert job["result"]["reply"] == "pg reminder"
