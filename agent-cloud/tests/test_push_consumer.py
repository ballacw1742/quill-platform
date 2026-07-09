"""Tests for ProactivePushConsumer (§9 Wave 2, MIGRATION.md §3.1)."""

from __future__ import annotations

import json
import pytest

from app import events as events_mod
from app.channels.base import SendResult, set_send_client
from app.events import InlineBus, make_event, reset_bus
from app.push_consumer import ProactivePushConsumer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockSendClient:
    """Captures outbound channel send calls."""

    def __init__(self):
        self.calls: list[dict] = []

    async def post(self, url: str, *, json: dict, headers: dict):
        self.calls.append({"url": url, "json": json, "headers": headers})

        class _FakeResp:
            status_code = 200

        return _FakeResp()


def _agent_response_event(
    *,
    tenant_id: str = "test-tenant",
    platform: str = "telegram",
    chat_id: str = "99999",
    text: str = "Good morning!",
) -> dict:
    return make_event(
        tenant_id=tenant_id,
        type="agent.response",
        payload={
            "text": text,
            "channel_target": {"platform": platform, "chat_id": chat_id},
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_consumer_registers_on_inline_bus():
    """start() adds the callback to InlineBus._subscribers."""
    bus = InlineBus()
    events_mod._bus = bus
    consumer = ProactivePushConsumer()
    await consumer.start()
    assert consumer._registered
    assert consumer._handle_event in bus._subscribers
    await consumer.stop()


async def test_consumer_deregisters_on_stop():
    bus = InlineBus()
    events_mod._bus = bus
    consumer = ProactivePushConsumer()
    await consumer.start()
    await consumer.stop()
    assert not consumer._registered
    assert consumer._handle_event not in bus._subscribers


async def test_consumer_delivers_to_telegram(monkeypatch):
    """An agent.response event with channel_target triggers a send call."""
    mock_client = _MockSendClient()
    set_send_client(lambda: mock_client)
    try:
        # Configure TELEGRAM_BOT_TOKEN so the adapter can send
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
        from app.config import get_settings
        get_settings.cache_clear()

        bus = InlineBus()
        events_mod._bus = bus
        consumer = ProactivePushConsumer()
        await consumer.start()

        event = _agent_response_event(platform="telegram", chat_id="12345", text="Hello!")
        await bus.publish(event)

        assert len(mock_client.calls) == 1
        call = mock_client.calls[0]
        assert "sendMessage" in call["url"]
        assert call["json"]["chat_id"] == "12345"
        assert call["json"]["text"] == "Hello!"

        await consumer.stop()
    finally:
        set_send_client(None)
        from app.config import get_settings
        get_settings.cache_clear()


async def test_consumer_ignores_non_agent_response_events():
    """Events of other types are silently ignored."""
    mock_client = _MockSendClient()
    set_send_client(lambda: mock_client)
    try:
        bus = InlineBus()
        events_mod._bus = bus
        consumer = ProactivePushConsumer()
        await consumer.start()

        # Emit a turn.completed event — should not trigger a send
        ev = make_event(
            tenant_id="test-tenant",
            type="turn.completed",
            payload={"model": "test", "tool_calls": [], "input_tokens": 10, "output_tokens": 10, "cost_usd": 0.0, "budget_exceeded": False},
        )
        await bus.publish(ev)

        assert len(mock_client.calls) == 0
        await consumer.stop()
    finally:
        set_send_client(None)


async def test_consumer_ignores_event_without_channel_target():
    """agent.response with no channel_target is safely ignored."""
    mock_client = _MockSendClient()
    set_send_client(lambda: mock_client)
    try:
        bus = InlineBus()
        events_mod._bus = bus
        consumer = ProactivePushConsumer()
        await consumer.start()

        ev = make_event(
            tenant_id="test-tenant",
            type="agent.response",
            payload={"text": "no target here"},
        )
        await bus.publish(ev)

        assert len(mock_client.calls) == 0
        await consumer.stop()
    finally:
        set_send_client(None)


async def test_consumer_ignores_unknown_platform():
    """agent.response with an unknown platform logs and does not crash."""
    mock_client = _MockSendClient()
    set_send_client(lambda: mock_client)
    try:
        bus = InlineBus()
        events_mod._bus = bus
        consumer = ProactivePushConsumer()
        await consumer.start()

        ev = make_event(
            tenant_id="test-tenant",
            type="agent.response",
            payload={
                "text": "hi",
                "channel_target": {"platform": "signal", "chat_id": "abc"},
            },
        )
        await bus.publish(ev)

        assert len(mock_client.calls) == 0
        await consumer.stop()
    finally:
        set_send_client(None)


async def test_pubsub_bus_consumer_noop():
    """ProactivePushConsumer is a no-op for PubSubBus (no subscribe hook)."""
    from app.events import PubSubBus

    # Minimal PubSubBus stub (no real client needed — no publish called)
    class _FakePubSubBus(PubSubBus):
        name = "pubsub"

        def __init__(self):
            super().__init__(client_factory=lambda: None)

    fake_bus = _FakePubSubBus()
    events_mod._bus = fake_bus

    consumer = ProactivePushConsumer()
    # Should not raise and not set _registered
    await consumer.start()
    assert not consumer._registered
    await consumer.stop()  # stop on non-registered is a no-op


def test_inline_bus_subscribe_unsubscribe():
    """InlineBus.subscribe / unsubscribe are additive and safe to call."""
    bus = InlineBus()
    calls: list[dict] = []

    def cb(ev: dict) -> None:
        calls.append(ev)

    bus.subscribe(cb)
    assert cb in bus._subscribers

    bus.unsubscribe(cb)
    assert cb not in bus._subscribers

    # Double-unsubscribe is a no-op.
    bus.unsubscribe(cb)


async def test_inline_bus_dispatches_to_subscriber():
    """Publishing an event calls registered subscribers."""
    bus = InlineBus()
    received: list[dict] = []

    def cb(ev: dict) -> None:
        received.append(ev)

    bus.subscribe(cb)
    ev = make_event(tenant_id="t", type="agent.response", payload={"text": "x"})
    await bus.publish(ev)
    assert len(received) == 1
    assert received[0]["type"] == "agent.response"
