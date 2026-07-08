"""Per-tenant rate limits (LIMITS.md §3) — fixed-window, fake clock."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

import app.orchestrator as orch_mod
from app import events as events_mod
from app import ratelimit as rl
from app.api import app
from app.config import get_settings
from tests.conftest import FakeProvider, text_response


@pytest.fixture(autouse=True)
def _reset_clock():
    rl.set_clock(None)
    yield
    rl.set_clock(None)


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class FakeClock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float):
        self.now = self.now + timedelta(seconds=seconds)


async def test_allows_up_to_limit_then_rejects(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "3")
    get_settings.cache_clear()
    clock = FakeClock(datetime(2026, 7, 7, 12, 0, 30, tzinfo=timezone.utc))
    rl.set_clock(clock)
    try:
        t = "smoke-rl-basic"
        # 3 allowed
        for _ in range(3):
            await rl.enforce(t, "chat")
        # 4th rejected
        with pytest.raises(rl.RateLimitExceeded) as ei:
            await rl.enforce(t, "chat")
        assert ei.value.decision.retry_after_seconds == 30  # 60 - 30s in
        assert ei.value.decision.limit == 3
    finally:
        get_settings.cache_clear()


async def test_window_reset_allows_again(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
    get_settings.cache_clear()
    clock = FakeClock(datetime(2026, 7, 7, 12, 0, 10, tzinfo=timezone.utc))
    rl.set_clock(clock)
    try:
        t = "smoke-rl-window"
        await rl.enforce(t, "chat")
        await rl.enforce(t, "chat")
        with pytest.raises(rl.RateLimitExceeded):
            await rl.enforce(t, "chat")
        # advance into the next minute window
        clock.advance(60)
        await rl.enforce(t, "chat")  # allowed again
    finally:
        get_settings.cache_clear()


async def test_zero_disables_bucket(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "0")
    get_settings.cache_clear()
    try:
        t = "smoke-rl-off"
        for _ in range(50):
            await rl.enforce(t, "chat")  # never raises
    finally:
        get_settings.cache_clear()


async def test_event_emitted_once_per_window(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    get_settings.cache_clear()
    clock = FakeClock(datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc))
    rl.set_clock(clock)
    try:
        t = "smoke-rl-event"
        await rl.enforce(t, "chat")  # allowed
        for _ in range(5):
            with pytest.raises(rl.RateLimitExceeded):
                await rl.enforce(t, "chat")
        bus = events_mod.get_bus()
        evs = [e for e in bus.published if e["type"] == "rate_limit.exceeded"]
        assert len(evs) == 1  # only the FIRST rejection of the window
        assert evs[0]["payload"]["bucket"] == "chat"
        assert evs[0]["payload"]["limit_per_min"] == 1
    finally:
        get_settings.cache_clear()


async def test_buckets_are_independent(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    monkeypatch.setenv("RATE_LIMIT_JOBS_PER_MIN", "1")
    get_settings.cache_clear()
    clock = FakeClock(datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc))
    rl.set_clock(clock)
    try:
        t = "smoke-rl-buckets"
        await rl.enforce(t, "chat")
        await rl.enforce(t, "jobs")  # different bucket, own counter
        with pytest.raises(rl.RateLimitExceeded):
            await rl.enforce(t, "chat")
    finally:
        get_settings.cache_clear()


async def test_tenants_are_independent(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    get_settings.cache_clear()
    clock = FakeClock(datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc))
    rl.set_clock(clock)
    try:
        await rl.enforce("smoke-rl-t1", "chat")
        await rl.enforce("smoke-rl-t2", "chat")  # different tenant, own counter
        with pytest.raises(rl.RateLimitExceeded):
            await rl.enforce("smoke-rl-t1", "chat")
    finally:
        get_settings.cache_clear()


async def test_chat_endpoint_returns_429_with_retry_after(monkeypatch, client):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    get_settings.cache_clear()
    clock = FakeClock(datetime(2026, 7, 7, 12, 0, 15, tzinfo=timezone.utc))
    rl.set_clock(clock)
    provider = FakeProvider([text_response("ok"), text_response("ok2")])
    monkeypatch.setattr(orch_mod, "get_provider", lambda *a, **k: provider)
    try:
        async with client:
            r1 = await client.post(
                "/v1/agents/chat",
                json={"tenant_id": "smoke-rl-http", "agent_id": "personal", "message": "hi"},
            )
            assert r1.status_code == 200
            r2 = await client.post(
                "/v1/agents/chat",
                json={"tenant_id": "smoke-rl-http", "agent_id": "personal", "message": "hi"},
            )
        assert r2.status_code == 429
        assert "detail" in r2.json()
        assert int(r2.headers["Retry-After"]) >= 1
    finally:
        get_settings.cache_clear()
