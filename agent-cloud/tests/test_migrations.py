"""Migration idempotency (LIMITS.md / SECRETS.md additive DDL).

- sqlite: run_migrations uses ORM create_all; assert it is safe to run twice
  and that the B2 ORM tables exist.
- postgres (gated on AGENTCLOUD_TEST_PG_DSN): run the full additive DDL twice
  and assert the B2 column + tables + RLS are present and stable.
"""

import os

import pytest


async def test_sqlite_create_all_idempotent():
    from app.db import engine
    from app.migrations import run_migrations

    # conftest already created the schema; running again must not error.
    await run_migrations(engine)
    await run_migrations(engine)

    from sqlalchemy import inspect

    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    assert "agentcloud_rate_limits" in tables
    assert "agentcloud_tenant_secrets" in tables
    assert "agentcloud_channel_links" in tables  # Phase D
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda c: [x["name"] for x in inspect(c).get_columns("agentcloud_tenants")]
        )
    assert "budget_monthly_usd" in cols


PG_DSN = os.environ.get("AGENTCLOUD_TEST_PG_DSN")


@pytest.mark.skipif(not PG_DSN, reason="AGENTCLOUD_TEST_PG_DSN not set (needs Postgres)")
async def test_pg_migrations_run_twice_idempotent():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db import normalize_dsn
    from app.migrations import run_migrations

    engine = create_async_engine(normalize_dsn(PG_DSN))
    try:
        await run_migrations(engine)
        await run_migrations(engine)  # second run must be a no-op, not error
        async with engine.begin() as conn:
            # B2 column present
            col = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name='agentcloud_tenants' "
                        "AND column_name='budget_monthly_usd'"
                    )
                )
            ).scalar_one()
            assert col == 1
            # B2 + D tables present + RLS forced
            for tbl in (
                "agentcloud_rate_limits",
                "agentcloud_tenant_secrets",
                "agentcloud_channel_links",  # Phase D
            ):
                forced = (
                    await conn.execute(
                        text(
                            "SELECT relforcerowsecurity FROM pg_class "
                            "WHERE relname = :t"
                        ),
                        {"t": tbl},
                    )
                ).scalar_one()
                assert forced is True
    finally:
        await engine.dispose()
