"""Scheduler + Daily Brief tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from quill_bot.scheduler import (
    QuillScheduler,
    _age_hours,
    escalate_lane2_8h,
    escalate_lane3_12h,
    fetch_daily_brief_inputs,
    remind_lane2_4h,
    render_brief_fallback,
    run_daily_brief,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _aged(hours: float, lane: int = 2, ap_id: str | None = None) -> dict:
    created = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    return {
        "id": ap_id or f"ap-{int(hours*10)}",
        "lane": lane,
        "workflow": "rfi.classify",
        "agent_confidence": 0.6,
        "sla_due_at": None,
        "priority": "normal",
        "payload": {},
        "created_at": created,
    }


def test_age_hours():
    item = _aged(2.5)
    a = _age_hours(item)
    assert a is not None
    assert 2.4 < a < 2.6


def test_age_hours_handles_z_suffix():
    item = {"created_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")}
    a = _age_hours(item)
    assert a is not None
    assert 0.9 < a < 1.1


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------
async def test_remind_lane2_4h_only_fires_for_4_to_8h(fake_api, fake_send):
    fake_api.pending = [
        _aged(2),    # too young
        _aged(5),    # in window
        _aged(7.5),  # in window
        _aged(9),    # too old (handled by escalate_lane2_8h)
    ]
    n = await remind_lane2_4h(fake_api, fake_send, "chat-1")
    assert n == 2
    assert fake_send.sent
    assert "2 item" in fake_send.sent[0][1]


async def test_escalate_lane2_8h(fake_api, fake_send):
    fake_api.pending = [_aged(5), _aged(9), _aged(13)]
    n = await escalate_lane2_8h(fake_api, fake_send, "chat-1")
    assert n == 2
    assert fake_send.sent


async def test_escalate_lane3_12h(fake_api, fake_send):
    fake_api.pending = [_aged(13, lane=3), _aged(20, lane=3), _aged(5, lane=3)]
    n = await escalate_lane3_12h(fake_api, fake_send, "chat-1")
    assert n == 2


async def test_remind_lane2_4h_empty(fake_api, fake_send):
    fake_api.pending = [_aged(1)]
    n = await remind_lane2_4h(fake_api, fake_send, "chat-1")
    assert n == 0
    assert fake_send.sent == []


# ---------------------------------------------------------------------------
# Daily brief
# ---------------------------------------------------------------------------
async def test_fetch_daily_brief_inputs(fake_api):
    fake_api.pending = [
        _aged(0.5),
        {**_aged(0.5, ap_id="cp-1"), "payload": {"critical_path": True}},
    ]
    inputs = await fetch_daily_brief_inputs(fake_api)
    assert "fleet_health" in inputs
    assert inputs["pending_count"] == 2
    assert len(inputs["critical_path_flags"]) == 1
    assert inputs["weather"]["location"] == "New Albany, OH"


def test_render_brief_fallback_handles_empty():
    md = render_brief_fallback({"date": "2026-05-08", "fleet_health": {}, "pending_approvals": []})
    assert "Quill Daily Brief" in md
    assert "Nothing pending" in md


def test_render_brief_fallback_lists_pending():
    md = render_brief_fallback(
        {
            "date": "2026-05-08",
            "fleet_health": {"db": "ok", "audit_chain": "ok"},
            "pending_approvals": [_aged(0.5, ap_id="x" * 8)],
            "critical_path_flags": [],
        }
    )
    assert "Pending approvals" in md
    assert "rfi.classify" in md


async def test_run_daily_brief_fallback_path(monkeypatch, bot_config, fake_api, fake_send):
    # Force runtime invocation to return None (so fallback is used).
    from quill_bot import scheduler as sch

    async def no_runtime(inputs, *, command_template):
        return None

    monkeypatch.setattr(sch, "render_brief_via_runtime", no_runtime)

    # Use a tmp drive root by overriding the gog command via PATH wipe.
    monkeypatch.setenv("PATH", "/nonexistent")
    bot_config.daily_brief_chat_id = "chat-1"

    result = await run_daily_brief(bot_config, fake_api, fake_send)
    assert result["ok"] is True
    assert result["delivered"] is True
    assert result["fallback_used"] is True
    assert fake_send.sent


async def test_run_daily_brief_no_chat_id_skips_send(monkeypatch, bot_config, fake_api, fake_send):
    from quill_bot import scheduler as sch

    async def no_runtime(inputs, *, command_template):
        return None

    monkeypatch.setattr(sch, "render_brief_via_runtime", no_runtime)
    monkeypatch.setenv("PATH", "/nonexistent")
    bot_config.daily_brief_chat_id = ""
    result = await run_daily_brief(bot_config, fake_api, fake_send)
    assert result["delivered"] is False
    assert fake_send.sent == []


# ---------------------------------------------------------------------------
# Scheduler integration
# ---------------------------------------------------------------------------
async def test_scheduler_jobs_snapshot_includes_daily_brief(bot_config, fake_api, fake_send):
    sch = QuillScheduler(bot_config, fake_api, fake_send)
    sch.schedule_all()  # add_job's without start() is fine for snapshotting

    snap = sch.jobs_snapshot()
    ids = {j["id"] for j in snap}
    assert "daily-brief-deliver" in ids
    assert "daily-brief-fetch" in ids
    assert "lane2-reminder-4h" in ids
    assert "lane2-escalate-8h" in ids
    assert "lane3-escalate-12h" in ids

    # next_run_at for daily-brief-deliver should be tomorrow 07:00 ET (or today if before 7am)
    deliver = next(j for j in snap if j["id"] == "daily-brief-deliver")
    assert deliver["next_run_at"] is not None
    # APScheduler computes seconds-precision; verify at minute granularity
    next_run = datetime.fromisoformat(deliver["next_run_at"])
    assert next_run.minute == 0


async def test_scheduler_pushes_heartbeat(bot_config, fake_api, fake_send):
    sch = QuillScheduler(bot_config, fake_api, fake_send)
    sch.schedule_all()
    await sch.push_heartbeat()
    assert len(fake_api.heartbeats) == 1
    ids = {j["id"] for j in fake_api.heartbeats[0]}
    assert "daily-brief-deliver" in ids
