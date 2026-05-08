"""Tests for the WS-event classifier + health-poll behavior."""

from __future__ import annotations

import asyncio
import pytest

from quill_bot.notifier import classify_event, poll_health


def test_classify_lane1_skipped():
    assert classify_event({"type": "approval.created", "lane": 1, "id": "a", "workflow": "x"}) is None


def test_classify_lane2_silent():
    n = classify_event({
        "type": "approval.created",
        "lane": 2,
        "id": "abcd1234efgh",
        "workflow": "rfi.classify",
        "priority": "normal",
        "payload": {},
    })
    assert n is not None
    assert n.silent is True
    assert "Lane 2" in n.text


def test_classify_lane3_loud():
    n = classify_event({
        "type": "approval.created",
        "lane": 3,
        "id": "abcd1234efgh",
        "workflow": "schedule.update",
        "priority": "normal",
        "payload": {},
    })
    assert n is not None
    assert n.silent is False
    assert "Lane 3" in n.text


def test_classify_safety_flag_overrides_silence():
    n = classify_event({
        "type": "approval.created",
        "lane": 2,
        "id": "abcd1234efgh",
        "workflow": "rfi.classify",
        "priority": "normal",
        "payload": {"safety_critical": True},
    })
    assert n is not None
    assert n.silent is False
    assert "🚨" in n.text
    assert "safety" in n.text


def test_classify_critical_path():
    n = classify_event({
        "type": "approval.created",
        "lane": 2,
        "id": "x" * 8,
        "workflow": "schedule.update",
        "priority": "normal",
        "payload": {"critical_path": True},
    })
    assert n is not None
    assert n.silent is False
    assert "critical-path" in n.text


def test_classify_decided_event():
    n = classify_event({
        "type": "approval.decided",
        "id": "abcd1234efgh",
        "lane": 2,
        "workflow": "rfi.classify",
        "decision": "approve",
    })
    assert n is not None
    assert n.silent is True
    assert "✅" in n.text


def test_classify_sla_breach():
    n = classify_event({
        "type": "approval.sla_breach",
        "id": "abcd1234efgh",
        "lane": 2,
        "workflow": "rfi.classify",
    })
    assert n is not None
    assert "⏰" in n.text


def test_classify_unknown_type_none():
    assert classify_event({"type": "approval.unknown"}) is None


# ---------------------------------------------------------------------------
# poll_health
# ---------------------------------------------------------------------------
async def test_poll_health_alerts_on_audit_break(bot_config, fake_api, fake_send):
    # First poll: ok. Second poll: broken.
    states = [
        {"ok": True, "audit_chain": "ok", "sla_breaches_open": 0},
        {"ok": True, "audit_chain": "broken", "sla_breaches_open": 0},
    ]
    idx = {"i": 0}

    async def fake_health() -> dict:
        s = states[idx["i"]]
        idx["i"] = min(idx["i"] + 1, len(states) - 1)
        return s

    fake_api.health = fake_health  # type: ignore[assignment]
    bot_config.poll_interval_health_s = 0  # tight loop for the test

    stop = asyncio.Event()

    async def runner():
        await poll_health(
            bot_config, fake_api, target_chat_id="chat-1", send=fake_send, stop_event=stop
        )

    task = asyncio.create_task(runner())
    # Let it tick a few times
    await asyncio.sleep(0.05)
    stop.set()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
        await asyncio.sleep(0)

    texts = [t for _, t, _ in fake_send.sent]
    assert any("Audit chain BROKEN" in t for t in texts), texts
