"""Sprint-4 scheduler hardening tests.

Covers:
  - Idempotent reminders survive a bot restart (fix #1).
  - Daily Brief queue: success path delivers (fix #3).
  - Daily Brief queue: timeout path falls back (fix #3).
  - Daily Brief queue: bounded \u2014 second enqueue while worker stalled is dropped (fix #3).
  - Concurrent Telegram + Drive: Drive failure does not block Telegram (fix #5).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from quill_bot import scheduler as sch
from quill_bot.dedup import DedupStore, reset_store_for_tests
from quill_bot.scheduler import (
    DailyBriefJob,
    DailyBriefQueue,
    escalate_lane2_8h,
    remind_lane2_4h,
    run_daily_brief,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _aged(hours: float, lane: int = 2, ap_id: str = "ap-x") -> dict[str, Any]:
    created = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    return {
        "id": ap_id,
        "lane": lane,
        "workflow": "rfi.classify",
        "agent_confidence": 0.6,
        "created_at": created,
    }


# ---------------------------------------------------------------------------
# Fix #1: idempotent reminders survive restart
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reminder_fires_once_then_no_ops(
    fake_api, fake_send, tmp_path: Path
) -> None:
    db = tmp_path / "dedup.db"
    s1 = DedupStore(db)

    fake_api.pending = [_aged(5, ap_id="ap-1"), _aged(6, ap_id="ap-2")]

    n1 = await remind_lane2_4h(fake_api, fake_send, "chat-1", store=s1)
    assert n1 == 2, "first scheduler tick should fire reminders"

    n2 = await remind_lane2_4h(fake_api, fake_send, "chat-1", store=s1)
    assert n2 == 0, "second tick same window should be a no-op"

    # Bot restart: brand-new store on the same db file
    s1.close()
    s2 = DedupStore(db)
    n3 = await remind_lane2_4h(fake_api, fake_send, "chat-1", store=s2)
    assert n3 == 0, "after restart we still must not re-nudge already-sent reminders"


@pytest.mark.asyncio
async def test_lane2_4h_and_lane2_8h_are_independent(
    fake_api, fake_send, tmp_path: Path
) -> None:
    s = DedupStore(tmp_path / "dedup.db")
    fake_api.pending = [_aged(5, ap_id="ap-a")]
    assert await remind_lane2_4h(fake_api, fake_send, "c", store=s) == 1
    # Same approval ages into the 8h window \u2014 different reminder kind \u2014 should fire
    fake_api.pending = [_aged(9, ap_id="ap-a")]
    assert await escalate_lane2_8h(fake_api, fake_send, "c", store=s) == 1


# ---------------------------------------------------------------------------
# Fix #3: Daily Brief async queue + timeout fallback
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_daily_brief_queue_success_path(
    bot_config, fake_api, fake_send, monkeypatch
) -> None:
    async def fake_runtime(inputs, *, command_template, timeout):
        return "# Brief\nFresh from runtime."

    async def fake_drive(_config, _date, _content):
        return "drive:/Quill/briefs/test.md"

    monkeypatch.setattr(sch, "render_brief_via_runtime", fake_runtime)
    monkeypatch.setattr(sch, "archive_brief_to_drive", fake_drive)

    queue = DailyBriefQueue(maxsize=2)
    await queue.start()
    try:
        ok = await queue.enqueue(
            DailyBriefJob(
                enqueued_at=datetime.now(UTC),
                config=bot_config,
                api=fake_api,
                send=fake_send,
            )
        )
        assert ok is True
        # Wait for the worker to drain
        for _ in range(50):
            if queue.last_result is not None:
                break
            await asyncio.sleep(0.02)
    finally:
        await queue.stop()

    assert queue.last_result is not None
    assert queue.last_result["ok"] is True
    assert queue.last_result["delivered"] is True
    assert queue.last_result["fallback_used"] is False
    assert any("Fresh from runtime" in t for _, t, _ in fake_send.sent)


@pytest.mark.asyncio
async def test_daily_brief_timeout_triggers_fallback(
    bot_config, fake_api, fake_send, monkeypatch
) -> None:
    async def slow_runtime(inputs, *, command_template, timeout):
        # Caller requested a short timeout; we honor it by returning None.
        await asyncio.sleep(0.01)
        return None  # simulates having already raised TimeoutError + handled it

    async def fake_drive(_config, _date, _content):
        return "drive:/fallback.md"

    monkeypatch.setattr(sch, "render_brief_via_runtime", slow_runtime)
    monkeypatch.setattr(sch, "archive_brief_to_drive", fake_drive)

    result = await run_daily_brief(
        bot_config, fake_api, fake_send, runtime_timeout=0.1
    )
    assert result["fallback_used"] is True
    assert result["delivered"] is True
    assert any("Quill Daily Brief" in t for _, t, _ in fake_send.sent)


@pytest.mark.asyncio
async def test_daily_brief_queue_is_bounded(
    bot_config, fake_api, fake_send, monkeypatch
) -> None:
    blocker = asyncio.Event()

    async def slow_runtime(inputs, *, command_template, timeout):
        await blocker.wait()
        return "# brief"

    async def fake_drive(_config, _date, _content):
        return "drive:/x.md"

    monkeypatch.setattr(sch, "render_brief_via_runtime", slow_runtime)
    monkeypatch.setattr(sch, "archive_brief_to_drive", fake_drive)

    queue = DailyBriefQueue(maxsize=1)
    await queue.start()
    try:
        # First enqueue takes the worker; subsequent enqueues fill the queue.
        first = await queue.enqueue(
            DailyBriefJob(datetime.now(UTC), bot_config, fake_api, fake_send)
        )
        # Give worker a moment to grab it off the queue
        await asyncio.sleep(0.05)
        # Two more: one fills the slot, one overflows.
        second = await queue.enqueue(
            DailyBriefJob(datetime.now(UTC), bot_config, fake_api, fake_send)
        )
        third = await queue.enqueue(
            DailyBriefJob(datetime.now(UTC), bot_config, fake_api, fake_send)
        )
        assert first is True
        assert second is True
        assert third is False, "queue should have rejected the overflow job"
    finally:
        blocker.set()
        await queue.stop()


# ---------------------------------------------------------------------------
# Fix #5: Drive failure does not block Telegram delivery
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_drive_failure_does_not_block_telegram(
    bot_config, fake_api, fake_send, monkeypatch
) -> None:
    async def good_runtime(inputs, *, command_template, timeout):
        return "# Brief\n\nHello."

    async def broken_drive(_config, _date, _content):
        raise RuntimeError("Drive 503")

    monkeypatch.setattr(sch, "render_brief_via_runtime", good_runtime)
    monkeypatch.setattr(sch, "archive_brief_to_drive", broken_drive)

    result = await run_daily_brief(bot_config, fake_api, fake_send)
    # Telegram still delivered, archive surfaces an error string \u2014 not an exception.
    assert result["delivered"] is True
    assert "error:" in str(result["archive"]).lower()
    assert any("Hello" in t for _, t, _ in fake_send.sent)
