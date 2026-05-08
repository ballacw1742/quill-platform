"""SQLAlchemy 2.0 async engine + session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

_settings = get_settings()


class Base(DeclarativeBase):
    """Common declarative base."""


def _engine_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {"echo": False, "future": True}
    if _settings.is_sqlite:
        # SQLite + aiosqlite doesn't support the default pool args nicely.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
    return kwargs


engine: AsyncEngine = create_async_engine(_settings.DATABASE_URL, **_engine_kwargs())

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine, expire_on_commit=False, class_=AsyncSession
)


async def get_db() -> AsyncIterator[AsyncSession]:
    # Look up SessionLocal at call time so test monkeypatches are honored.
    import sys

    sm = sys.modules[__name__].SessionLocal
    async with sm() as session:
        try:
            yield session
        finally:
            await session.close()


async def connect() -> None:
    """Eagerly verify the connection on startup."""
    import sys

    eng = sys.modules[__name__].engine
    async with eng.connect() as conn:
        await conn.exec_driver_sql("SELECT 1")


async def disconnect() -> None:
    import sys

    eng = sys.modules[__name__].engine
    await eng.dispose()
