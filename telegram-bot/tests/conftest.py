"""Shared bot test fixtures."""

from __future__ import annotations

import os
from typing import Any

import pytest

# Force fake-token mode for all tests
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("QUILL_BOT_FAKE_MODE", "1")
os.environ.setdefault("TELEGRAM_PAIRING_SECRET", "test-pair-secret")
os.environ.setdefault("AGENT_SHARED_SECRET", "test-agent-secret")
os.environ.setdefault("DEEPLINK_SIGNING_SECRET", "test-deeplink-secret")
os.environ.setdefault("DAILY_BRIEF_CHAT_ID", "1234567")
os.environ.setdefault("QUILL_API_URL", "http://test-api")
os.environ.setdefault("QUILL_WEB_BASE_URL", "https://web.test")


from quill_bot.config import BotConfig  # noqa: E402
from quill_bot.dedup import reset_store_for_tests  # noqa: E402


@pytest.fixture
def bot_config() -> BotConfig:
    return BotConfig.from_env()


@pytest.fixture(autouse=True)
def _isolated_dedup_store(tmp_path):
    """Each test gets a brand-new SQLite dedup file so reminder/pairing
    rows from previous tests don't bleed across."""
    reset_store_for_tests(tmp_path / "bot-dedup.db")
    yield


class FakeAPIClient:
    """In-memory test double for QuillAPIClient."""

    def __init__(self) -> None:
        self.pending: list[dict[str, Any]] = []
        self.health_state: dict[str, Any] = {
            "ok": True,
            "db": "ok",
            "queue_depth_pending": 0,
            "queue_depth_executed": 0,
            "audit_chain": "ok",
            "audit_chain_length": 0,
            "sla_breaches_open": 0,
            "version": "0.1.0",
        }
        self.heartbeats: list[list[dict[str, Any]]] = []
        self.pair_calls: list[dict[str, Any]] = []
        self.pair_response: dict[str, Any] = {
            "ok": True,
            "user_id": "u-1",
            "email": "charles@example.com",
            "telegram_chat_id": "1234567",
        }
        self.pair_error: Exception | None = None

    async def list_pending(
        self, *, lane: int | None = None, limit: int = 5, offset: int = 0
    ) -> list[dict[str, Any]]:
        items = [
            it for it in self.pending if (lane is None or it.get("lane") == lane)
        ]
        return items[offset : offset + limit]

    async def get_approval(self, approval_id: str) -> dict[str, Any]:
        for it in self.pending:
            if it.get("id") == approval_id:
                return it
        from quill_bot.api_client import QuillAPIError

        raise QuillAPIError(404, "not found")

    async def cancel(self, approval_id: str, reason: str | None = None) -> dict[str, Any]:
        return {"id": approval_id, "status": "cancelled", "reason": reason}

    async def health(self) -> dict[str, Any]:
        return self.health_state

    async def scheduler_heartbeat(self, jobs: list[dict[str, Any]]) -> dict[str, Any]:
        self.heartbeats.append(jobs)
        return {"ok": True, "received": len(jobs)}

    async def pair_user_telegram(
        self, email: str, chat_id: str, telegram_username: str | None = None
    ) -> dict[str, Any]:
        self.pair_calls.append(
            {"email": email, "chat_id": chat_id, "telegram_username": telegram_username}
        )
        if self.pair_error is not None:
            raise self.pair_error
        return {**self.pair_response, "email": email, "telegram_chat_id": chat_id}

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake_api() -> FakeAPIClient:
    return FakeAPIClient()


class FakeSender:
    """Captures send_message calls."""

    def __init__(self) -> None:
        self.sent: list[tuple[str | int, str, bool]] = []

    async def __call__(self, chat_id: str | int, text: str, silent: bool = False) -> None:
        self.sent.append((chat_id, text, silent))


@pytest.fixture
def fake_send() -> FakeSender:
    return FakeSender()
