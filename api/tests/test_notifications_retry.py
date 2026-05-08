"""Sprint-4 fix #4: with_retry helper covers the at-least-once semantic
for callers that POST to flaky endpoints (e.g. the bot's heartbeat path).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.services.notifications import with_retry


@pytest.mark.asyncio
async def test_with_retry_succeeds_first_attempt(monkeypatch):
    calls = {"n": 0}

    async def fast(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", fast)

    async def fn():
        calls["n"] += 1
        return "ok"

    ok, value, exc = await with_retry(fn, max_attempts=5)
    assert ok is True
    assert value == "ok"
    assert exc is None
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_with_retry_recovers_after_transient_failures(monkeypatch):
    calls = {"n": 0}

    async def fast(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", fast)

    async def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("boom")
        return "yay"

    ok, value, exc = await with_retry(fn, max_attempts=5, label="hb")
    assert ok is True
    assert value == "yay"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_with_retry_gives_up_and_logs_sentry(monkeypatch):
    captured: list[dict[str, Any]] = []

    from app.services import notifications as notif

    def fake_capture(message: str, *, level: str = "error", **tags: Any) -> str:
        captured.append({"message": message, "level": level, **tags})
        return "evt-id"

    async def fast(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", fast)
    monkeypatch.setattr(notif.sentry_svc, "capture_message", fake_capture)

    async def always_fails():
        raise httpx.ConnectError("nope")

    ok, value, exc = await with_retry(
        always_fails, max_attempts=3, label="heartbeat", sentry_event="hb.fail"
    )
    assert ok is False
    assert value is None
    assert isinstance(exc, httpx.ConnectError)
    assert len(captured) == 1
    assert captured[0]["message"] == "hb.fail"
    assert captured[0]["level"] == "error"


@pytest.mark.asyncio
async def test_with_retry_does_not_retry_on_4xx(monkeypatch):
    calls = {"n": 0}

    async def fast(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", fast)

    class FakeResponse:
        status_code = 400

    async def fn():
        calls["n"] += 1
        raise httpx.HTTPStatusError(
            "bad request", request=None, response=FakeResponse()  # type: ignore
        )

    ok, _, _ = await with_retry(fn, max_attempts=5, label="x")
    assert ok is False
    # 4xx is not retryable in our policy.
    assert calls["n"] == 1
