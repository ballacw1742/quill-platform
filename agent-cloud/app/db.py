"""Async SQLAlchemy engine + pooled sessions + per-request tenant GUC.

Isolation is enforced twice (design doc §6):
  1. App layer — every query filters tenant_id (repository discipline).
  2. Postgres RLS — all agentcloud_* tables have FORCE ROW LEVEL SECURITY
     with a policy on `current_setting('app.tenant_id', true)`. The GUC is
     set per-transaction (SET LOCAL semantics via set_config(..., true)),
     so pooled connections can't leak a tenant across requests.

Use `tenant_session(tenant_id)` for all request-path DB work.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def normalize_dsn(dsn: str) -> str:
    """Coerce whatever scheme the secret carries into an asyncpg URL.

    QUILL_DATABASE_URL is stored SQLAlchemy-style (postgresql+asyncpg://...);
    tolerate plain postgresql:// / postgres:// too.
    """
    if dsn.startswith("sqlite"):
        return dsn
    scheme, rest = dsn.split("://", 1)
    base = scheme.split("+", 1)[0]
    if base in ("postgresql", "postgres"):
        return f"postgresql+asyncpg://{rest}"
    return dsn


def _engine_kwargs(is_sqlite: bool) -> dict[str, Any]:
    s = get_settings()
    kwargs: dict[str, Any] = {"echo": False, "future": True}
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = s.DB_POOL_SIZE
        kwargs["max_overflow"] = s.DB_MAX_OVERFLOW
        kwargs["pool_recycle"] = s.DB_POOL_RECYCLE_SECONDS
    return kwargs


_settings = get_settings()

engine: AsyncEngine = create_async_engine(
    normalize_dsn(_settings.DATABASE_URL), **_engine_kwargs(_settings.is_sqlite)
)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine, expire_on_commit=False, class_=AsyncSession
)


def is_postgres() -> bool:
    return engine.dialect.name == "postgresql"


async def set_tenant_guc(session: AsyncSession, tenant_id: str) -> None:
    """SET LOCAL app.tenant_id for the current transaction (Postgres only)."""
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )


@asynccontextmanager
async def tenant_session(tenant_id: str) -> AsyncIterator[AsyncSession]:
    """One transaction, tenant GUC pinned. Commits on success, rolls back on error."""
    import sys

    sm = sys.modules[__name__].SessionLocal
    async with sm() as session:
        async with session.begin():
            await set_tenant_guc(session, tenant_id)
            yield session


@asynccontextmanager
async def admin_session() -> AsyncIterator[AsyncSession]:
    """Maintenance-path transaction: sets app.admin='on' (admin RLS policy).

    Never used on the request path — only by app/admin.py (Cloud Run job)
    and startup migrations.
    """
    import sys

    sm = sys.modules[__name__].SessionLocal
    async with sm() as session:
        async with session.begin():
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                await session.execute(
                    text("SELECT set_config('app.admin', 'on', true)")
                )
            yield session


async def ping() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False


async def dispose() -> None:
    await engine.dispose()
