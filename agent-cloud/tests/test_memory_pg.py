"""Postgres-gated memory tests: RLS on agentcloud_memory + pgvector search.

Skipped unless AGENTCLOUD_TEST_PG_DSN is set (same convention as
tests/test_rls_pg.py). pgvector-specific tests additionally skip when the
target Postgres lacks the vector extension (migrations degrade cleanly).
"""

import os
import uuid

import pytest

PG_DSN = os.environ.get("AGENTCLOUD_TEST_PG_DSN")

pytestmark = pytest.mark.skipif(
    not PG_DSN, reason="AGENTCLOUD_TEST_PG_DSN not set (needs Postgres)"
)

TENANT_A = "smoke-memrls-a"
TENANT_B = "smoke-memrls-b"


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
        for t in ("agentcloud_memory", "agentcloud_agents", "agentcloud_tenants"):
            await conn.execute(
                text(f"DELETE FROM {t} WHERE tenant_id LIKE 'smoke-memrls-%'")
            )
    await engine.dispose()


async def _seed(engine, tenant: str, content: str, embedding: list[float] | None = None):
    from sqlalchemy import text

    mid = uuid.uuid4()
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
                "INSERT INTO agentcloud_memory (memory_id, tenant_id, agent_id, content) "
                "VALUES (:m, :t, 'personal', :c)"
            ),
            {"m": mid, "t": tenant, "c": content},
        )
        if embedding is not None:
            vec = "[" + ",".join(str(x) for x in embedding) + "]"
            await conn.execute(
                text(
                    "UPDATE agentcloud_memory SET embedding = CAST(:v AS vector) "
                    "WHERE memory_id = :m"
                ),
                {"v": vec, "m": mid},
            )
    return mid


async def _has_vector(engine) -> bool:
    from sqlalchemy import text

    async with engine.begin() as conn:
        n = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE "
                    "table_name='agentcloud_memory' AND column_name='embedding'"
                )
            )
        ).scalar_one()
    return bool(n)


async def test_memory_rls_wrong_tenant_sees_zero_rows(pg_engine):
    from sqlalchemy import text

    await _seed(pg_engine, TENANT_A, "tenant A secret memory")
    async with pg_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT_B}
        )
        n = (
            await conn.execute(text("SELECT count(*) FROM agentcloud_memory"))
        ).scalar_one()
        assert n == 0
    # no GUC at all → zero rows too
    async with pg_engine.begin() as conn:
        n = (
            await conn.execute(text("SELECT count(*) FROM agentcloud_memory"))
        ).scalar_one()
        assert n == 0


async def test_memory_rls_correct_tenant_sees_own_rows(pg_engine):
    from sqlalchemy import text

    await _seed(pg_engine, TENANT_A, "tenant A visible memory")
    async with pg_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT_A}
        )
        n = (
            await conn.execute(text("SELECT count(*) FROM agentcloud_memory"))
        ).scalar_one()
        assert n >= 1


async def test_memory_rls_insert_wrong_tenant_rejected(pg_engine):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    await _seed(pg_engine, TENANT_A, "seed")
    with pytest.raises((DBAPIError, ProgrammingError)):
        async with pg_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT_B}
            )
            await conn.execute(
                text(
                    "INSERT INTO agentcloud_memory (tenant_id, agent_id, content) "
                    "VALUES (:t, 'personal', 'forged')"
                ),
                {"t": TENANT_A},
            )


async def test_pgvector_similarity_ordering(pg_engine):
    """Nearest-by-cosine ordering with hand-built vectors (no provider)."""
    if not await _has_vector(pg_engine):
        pytest.skip("pgvector extension unavailable on this Postgres")
    from sqlalchemy import text

    from app.config import get_settings

    dim = get_settings().EMBEDDING_DIM

    def unit(axis: int) -> list[float]:
        v = [0.0] * dim
        v[axis] = 1.0
        return v

    near = unit(0)
    far = unit(1)
    mid = [0.0] * dim
    mid[0] = 0.7
    mid[1] = 0.3

    await _seed(pg_engine, TENANT_A, "exact match", embedding=near)
    await _seed(pg_engine, TENANT_A, "partial match", embedding=mid)
    await _seed(pg_engine, TENANT_A, "orthogonal", embedding=far)
    await _seed(pg_engine, TENANT_B, "other tenant near", embedding=near)

    qvec = "[" + ",".join(str(x) for x in near) + "]"
    async with pg_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT_A}
        )
        rows = (
            await conn.execute(
                text(
                    "SELECT content FROM agentcloud_memory "
                    "WHERE tenant_id = :t AND agent_id = 'personal' "
                    "AND embedding IS NOT NULL "
                    "ORDER BY embedding <=> CAST(:v AS vector) LIMIT 3"
                ),
                {"t": TENANT_A, "v": qvec},
            )
        ).all()
    contents = [r[0] for r in rows]
    assert contents == ["exact match", "partial match", "orthogonal"]
    assert "other tenant near" not in contents  # namespace + RLS
