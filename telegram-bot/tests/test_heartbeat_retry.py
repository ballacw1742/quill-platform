"""Sprint-4 fix #4: heartbeat at-least-once delivery.

The bot's scheduler pushes its job snapshot to the API every 60s. If the
API is briefly unavailable we retry up to 5 times with exponential backoff
(1s, 2s, 4s, 8s, 16s), and on final failure we log a Sentry event but do
NOT raise \u2014 the heartbeat is non-critical.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from quill_bot.api_client import QuillAPIError
from quill_bot.scheduler import QuillScheduler


class CountingAPI:
    """Minimal API double that fails N times then succeeds."""

    def __init__(self, *, fail_status: int = 503, fail_times: int = 0) -> None:
        self.fail_status = fail_status
        self.fail_times = fail_times
        self.calls = 0

    async def scheduler_heartbeat(self, jobs: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise QuillAPIError(self.fail_status, "service unavailable")
        return {"ok": True, "received": len(jobs)}


async def _fast_sleep(_: float) -> None:
    """Skip the real backoff sleep so tests stay fast."""
    return None


@pytest.fixture
def patched_sleep(monkeypatch):
    import quill_bot.scheduler as sch

    monkeypatch.setattr(sch.asyncio, "sleep", _fast_sleep)


@pytest.mark.asyncio
async def test_heartbeat_succeeds_first_try(bot_config, fake_send, patched_sleep):
    api = CountingAPI(fail_times=0)
    s = QuillScheduler(bot_config, api, fake_send)
    s.schedule_all()
    await s.push_heartbeat()
    assert api.calls == 1


@pytest.mark.asyncio
async def test_heartbeat_recovers_after_transient_failures(
    bot_config, fake_send, patched_sleep
):
    api = CountingAPI(fail_status=503, fail_times=3)
    s = QuillScheduler(bot_config, api, fake_send)
    s.schedule_all()
    await s.push_heartbeat()
    # 3 failures + 1 success = 4 attempts
    assert api.calls == 4


@pytest.mark.asyncio
async def test_heartbeat_gives_up_after_5_attempts(
    bot_config, fake_send, patched_sleep
):
    api = CountingAPI(fail_status=503, fail_times=99)
    s = QuillScheduler(bot_config, api, fake_send)
    s.schedule_all()
    # Should NOT raise.
    await s.push_heartbeat()
    assert api.calls == 5


@pytest.mark.asyncio
async def test_heartbeat_does_not_retry_on_4xx(
    bot_config, fake_send, patched_sleep
):
    """4xx is a permanent error \u2014 don't keep trying."""
    api = CountingAPI(fail_status=403, fail_times=99)
    s = QuillScheduler(bot_config, api, fake_send)
    s.schedule_all()
    await s.push_heartbeat()
    # 4xx is not retryable per our policy
    assert api.calls == 1


@pytest.mark.asyncio
async def test_heartbeat_retries_on_network_error(
    bot_config, fake_send, patched_sleep
):
    """status=0 from the bot api_client signals a network/connection error."""
    api = CountingAPI(fail_status=0, fail_times=2)
    s = QuillScheduler(bot_config, api, fake_send)
    s.schedule_all()
    await s.push_heartbeat()
    assert api.calls == 3
