"""Handler-level tests using FakeAPIClient."""

from __future__ import annotations

import json

import pytest

from quill_bot.handlers import decisions, health, queue, start


# ---------------------------------------------------------------------------
# /start pairing
# ---------------------------------------------------------------------------
async def test_start_no_args_shows_welcome(bot_config, fake_api):
    reply = await start.handle_start(
        config=bot_config, api=fake_api, chat_id=999, args=[]
    )
    assert "pair" in reply.lower()


async def test_start_with_valid_code_pairs(bot_config, fake_api):
    from quill_bot.pairing import mint_code

    code = mint_code("charles@example.com", bot_config.telegram_pairing_secret)
    reply = await start.handle_start(
        config=bot_config,
        api=fake_api,
        chat_id=1234567,
        args=[code],
        telegram_username="cmitchell",
    )
    assert "paired" in reply.lower() or "connected" in reply.lower()
    assert len(fake_api.pair_calls) == 1
    call = fake_api.pair_calls[0]
    assert call["email"] == "charles@example.com"
    assert call["chat_id"] == "1234567"
    assert call["telegram_username"] == "cmitchell"


async def test_start_with_invalid_code_rejects(bot_config, fake_api):
    reply = await start.handle_start(
        config=bot_config, api=fake_api, chat_id=1, args=["bogus"]
    )
    assert "❌" in reply or "invalid" in reply.lower()
    assert len(fake_api.pair_calls) == 0


async def test_start_user_not_found(bot_config, fake_api):
    from quill_bot.api_client import QuillAPIError
    from quill_bot.pairing import mint_code

    fake_api.pair_error = QuillAPIError(404, "user not found")
    code = mint_code("ghost@example.com", bot_config.telegram_pairing_secret)
    reply = await start.handle_start(
        config=bot_config, api=fake_api, chat_id=1, args=[code]
    )
    assert "❌" in reply
    assert "ghost@example.com" in reply


# ---------------------------------------------------------------------------
# /queue
# ---------------------------------------------------------------------------
async def test_queue_empty(fake_api):
    reply = await queue.handle_queue(api=fake_api)
    assert "empty" in reply.lower() or "✅" in reply


async def test_queue_paginates(fake_api):
    fake_api.pending = [
        {
            "id": f"ap-{i:03d}-aaaaaa",
            "lane": 2,
            "workflow": "rfi.classify",
            "agent_confidence": 0.7,
            "sla_due_at": "2026-05-08T12:00:00Z",
            "priority": "normal",
            "payload": {},
        }
        for i in range(7)
    ]
    page1 = await queue.handle_queue(api=fake_api, page=0)
    assert "ap-000" in page1
    assert "ap-004" in page1
    # 5 per page → next-page hint
    assert "next" in page1.lower()
    page2 = await queue.handle_queue(api=fake_api, page=1)
    assert "ap-005" in page2
    assert "ap-006" in page2


async def test_queue_marks_critical_path(fake_api):
    fake_api.pending = [
        {
            "id": "ap-crit-aaaa",
            "lane": 3,
            "workflow": "schedule.update",
            "agent_confidence": 0.5,
            "sla_due_at": "2026-05-08T01:00:00Z",
            "priority": "critical",
            "payload": {"critical_path": True, "safety_critical": True},
        }
    ]
    reply = await queue.handle_queue(api=fake_api)
    assert "🚨" in reply
    assert "📍" in reply  # critical path
    assert "⚠️" in reply  # safety


# ---------------------------------------------------------------------------
# /approve, /reject, /edit, /escalate
# ---------------------------------------------------------------------------
@pytest.fixture
def pending_item(fake_api):
    item = {
        "id": "ap-12345678-aaaa",
        "lane": 2,
        "status": "pending",
        "workflow": "rfi.classify",
        "agent_confidence": 0.7,
        "payload": {"rfi_id": "RFI-1"},
    }
    fake_api.pending.append(item)
    return item


async def test_approve_returns_deeplink(bot_config, fake_api, pending_item):
    reply = await decisions.handle_approve(
        api=fake_api, config=bot_config, args=[pending_item["id"]], user_id="u-1"
    )
    assert "Approve" in reply
    assert bot_config.quill_web_base_url in reply
    assert "expires" in reply.lower()


async def test_approve_missing_id(bot_config, fake_api):
    reply = await decisions.handle_approve(
        api=fake_api, config=bot_config, args=[]
    )
    assert "Usage" in reply


async def test_approve_unknown_id(bot_config, fake_api):
    reply = await decisions.handle_approve(
        api=fake_api, config=bot_config, args=["missing"]
    )
    assert "❌" in reply


async def test_approve_already_decided(bot_config, fake_api, pending_item):
    pending_item["status"] = "executed"
    reply = await decisions.handle_approve(
        api=fake_api, config=bot_config, args=[pending_item["id"]]
    )
    assert "no longer pending" in reply


async def test_reject_requires_reason(bot_config, fake_api, pending_item):
    reply = await decisions.handle_reject(
        api=fake_api, config=bot_config, args=[pending_item["id"]]
    )
    assert "Usage" in reply


async def test_reject_with_reason_returns_deeplink(bot_config, fake_api, pending_item):
    reply = await decisions.handle_reject(
        api=fake_api,
        config=bot_config,
        args=[pending_item["id"], "scope", "creep"],
    )
    assert "scope creep" in reply
    assert bot_config.quill_web_base_url in reply


async def test_edit_returns_payload_preview(bot_config, fake_api, pending_item):
    reply = await decisions.handle_edit(
        api=fake_api, config=bot_config, args=[pending_item["id"]]
    )
    assert "RFI-1" in reply
    assert "Edit" in reply
    assert bot_config.quill_web_base_url in reply


async def test_escalate_requires_id(bot_config, fake_api):
    reply = await decisions.handle_escalate(
        api=fake_api, config=bot_config, args=[]
    )
    assert "Usage" in reply


async def test_escalate_already_lane3(bot_config, fake_api, pending_item):
    pending_item["lane"] = 3
    reply = await decisions.handle_escalate(
        api=fake_api, config=bot_config, args=[pending_item["id"]]
    )
    assert "already Lane 3" in reply


async def test_escalate_lane2(bot_config, fake_api, pending_item):
    reply = await decisions.handle_escalate(
        api=fake_api, config=bot_config, args=[pending_item["id"]]
    )
    assert "Escalate" in reply
    assert bot_config.quill_web_base_url in reply


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------
async def test_health_renders(fake_api):
    reply = await health.handle_health(api=fake_api)
    assert "fleet health" in reply.lower()
    assert "0.1.0" in reply


async def test_health_failure(fake_api):
    from quill_bot.api_client import QuillAPIError

    async def boom() -> dict:
        raise QuillAPIError(500, "db down")

    fake_api.health = boom  # type: ignore[assignment]
    reply = await health.handle_health(api=fake_api)
    assert "❌" in reply
    assert "500" in reply


def test_brief_no_archive_yet(tmp_path):
    reply = health.handle_brief(brief_root=tmp_path / "doesnotexist")
    assert "No Daily Brief" in reply or "📰" in reply


def test_brief_returns_latest(tmp_path):
    (tmp_path / "2026-05-01-daily.md").write_text("# old\n")
    (tmp_path / "2026-05-08-daily.md").write_text("# Today\nFleet OK.\n")
    reply = health.handle_brief(brief_root=tmp_path)
    assert "Today" in reply
    assert "2026-05-08" in reply
