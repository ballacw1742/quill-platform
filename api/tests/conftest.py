"""Test fixtures. Uses an in-memory SQLite per test for speed and isolation."""

from __future__ import annotations

import os

# Force test config BEFORE importing the app.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DATABASE_URL_SYNC", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("AGENT_SHARED_SECRET", "test-agent-secret")
os.environ.setdefault("CORS_ORIGINS", "http://localhost")

from collections.abc import AsyncIterator  # noqa: E402

import pytest_asyncio  # noqa: E402
from app import db as db_module  # noqa: E402
from app.db import Base  # noqa: E402
from app.enums import UserRole  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password, issue_token  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def client(engine, session_maker, monkeypatch) -> AsyncIterator[AsyncClient]:
    # Re-bind the app's session factory + engine to the test engine.
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_maker)

    # Reimport main AFTER monkeypatch so the app uses the patched module references.
    import importlib

    from app import main as main_module

    importlib.reload(main_module)

    transport = ASGITransport(app=main_module.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Manually trigger lifespan startup since ASGITransport doesn't
        async with main_module.app.router.lifespan_context(main_module.app):
            yield ac


@pytest_asyncio.fixture
async def owner_token(session_maker) -> tuple[str, str]:
    """Create an owner user, return (user_id, bearer_token)."""
    async with session_maker() as s:
        u = User(
            email="charles@test.local",
            display_name="Charles",
            role=UserRole.OWNER.value,
            password_hash=hash_password("test-pass-123"),
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u.id, issue_token(u)


@pytest_asyncio.fixture
async def partner_token(session_maker) -> tuple[str, str]:
    async with session_maker() as s:
        u = User(
            email="partner@test.local",
            display_name="Partner",
            role=UserRole.PARTNER.value,
            password_hash=hash_password("test-pass-123"),
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u.id, issue_token(u)


def auth_h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def agent_h() -> dict[str, str]:
    return {"X-Agent-Secret": os.environ["AGENT_SHARED_SECRET"]}


def admin_h() -> dict[str, str]:
    return {"X-Admin": os.environ["AGENT_SHARED_SECRET"]}
