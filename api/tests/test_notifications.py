"""Tests for app.services.notifications + admin notification endpoints."""

from __future__ import annotations

import pytest

from app.services import sentry as sentry_svc
from app.services.notifications import (
    EmailStubBackend,
    Notifier,
    TelegramBackend,
    TwilioStubBackend,
)
from tests.conftest import admin_h


# ---------------------------------------------------------------------------
# Backend unit tests
# ---------------------------------------------------------------------------
async def test_telegram_backend_missing_token_returns_failure():
    be = TelegramBackend(token="")
    res = await be.send("12345", "hi")  # real-looking chat_id triggers token check
    assert res.ok is False
    assert res.backend == "telegram"
    assert res.detail == "missing_token"


async def test_telegram_backend_fake_chat_id_short_circuits():
    be = TelegramBackend(token="fake-token-12345")
    res = await be.send("fake", "hi from test")
    assert res.ok is True
    assert res.detail == "fake"


async def test_twilio_stub_returns_success():
    res = await TwilioStubBackend().send("+15555550100", "ping")
    assert res.ok is True
    assert res.backend == "twilio_sms"
    assert res.detail == "stub"


async def test_email_stub_returns_success():
    res = await EmailStubBackend().send("ops@example.com", "ping")
    assert res.ok is True
    assert res.backend == "email"


async def test_notifier_sentry_event_no_dsn_still_succeeds():
    n = Notifier()
    res = await n.sentry_event("info", "unit test event", approval_id="abc-123")
    assert res.ok is True
    assert res.backend == "sentry"


async def test_notifier_drive_upload_falls_back_to_local(tmp_path, monkeypatch):
    n = Notifier()
    # Force gog missing by injecting an empty PATH dir.
    monkeypatch.setenv("PATH", str(tmp_path))
    res = await n.drive_upload("/Quill/briefs/unit-test.md", "# hello\n")
    assert res.ok is True
    assert res.backend == "drive"
    assert "fallback" in (res.detail or "")


# ---------------------------------------------------------------------------
# Sentry wrapper sanity
# ---------------------------------------------------------------------------
def test_sentry_init_idempotent_without_dsn():
    # Second init should not raise even when no DSN is set.
    sentry_svc.init(force=True)
    sentry_svc.init(force=True)
    sentry_svc.tag_request("rid-123")
    sentry_svc.tag_approval("ap-456")
    sentry_svc.tag_user("u-789")
    sentry_svc.tag_agent("ag-rfi-triage")
    eid = sentry_svc.capture_message("test", level="info", request_id="rid-1")
    # eid is None when no DSN is configured \u2014 that's the contract.
    assert eid is None or isinstance(eid, str)


def test_sentry_capture_exception_no_dsn():
    try:
        raise ValueError("synthetic")
    except ValueError as e:
        eid = sentry_svc.capture_exception(e)
    assert eid is None or isinstance(eid, str)


# ---------------------------------------------------------------------------
# Admin endpoint integration tests
# ---------------------------------------------------------------------------
async def test_admin_test_telegram_requires_admin(client):
    r = await client.get("/v1/admin/notifications/test_telegram", params={"chat_id": "fake"})
    assert r.status_code == 401


async def test_admin_test_telegram_fake_chat_id(client):
    r = await client.get(
        "/v1/admin/notifications/test_telegram",
        params={"chat_id": "fake", "text": "hello from sprint 2.4"},
        headers=admin_h(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["backend"] == "telegram"


async def test_admin_test_telegram_no_token_configured(client, monkeypatch):
    # If TELEGRAM_BOT_TOKEN is unset and chat_id is real, we expect ok=False
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    # Rebuild notifier to pick up the cleared env
    from app.services import notifications as notif_mod
    notif_mod.notifier.telegram = notif_mod.TelegramBackend(token="")
    r = await client.get(
        "/v1/admin/notifications/test_telegram",
        params={"chat_id": "12345"},
        headers=admin_h(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["detail"] == "missing_token"


async def test_admin_sentry_test_endpoint(client):
    r = await client.get(
        "/v1/admin/notifications/sentry_test",
        params={"level": "warning"},
        headers=admin_h(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "event_id" in body
    assert "exception_event_id" in body


async def test_admin_scheduler_jobs_lists_canonical(client):
    r = await client.get("/v1/admin/scheduler/jobs", headers=admin_h())
    assert r.status_code == 200, r.text
    body = r.json()
    assert "jobs" in body
    ids = {j["id"] for j in body["jobs"]}
    # The canonical schedule must always be present.
    assert "daily-brief-deliver" in ids
    assert "daily-brief-fetch" in ids
    assert "lane3-escalate-12h" in ids
    # Initially no bot heartbeat
    assert body["bot_connected"] is False


async def test_admin_scheduler_heartbeat_then_list(client):
    payload = {
        "jobs": [
            {
                "id": "daily-brief-deliver",
                "name": "Daily Brief delivery (overridden by bot)",
                "trigger": "cron(hour=7, minute=0)",
                "next_run_at": "2026-05-09T11:00:00+00:00",
                "last_status": "ok",
            },
            {
                "id": "approvals-ws-listener",
                "name": "WebSocket approvals consumer",
                "trigger": "longrunning",
                "next_run_at": None,
            },
        ]
    }
    r = await client.post(
        "/v1/admin/scheduler/jobs/heartbeat",
        json=payload,
        headers=admin_h(),
    )
    assert r.status_code == 200
    assert r.json()["received"] == 2

    r2 = await client.get("/v1/admin/scheduler/jobs", headers=admin_h())
    body = r2.json()
    assert body["bot_connected"] is True
    ids = {j["id"]: j for j in body["jobs"]}
    # bot's authoritative entry overwrote canonical for this id
    assert ids["daily-brief-deliver"]["source"] == "bot"
    # bot-only id is included
    assert "approvals-ws-listener" in ids


@pytest.mark.parametrize("bad_body", [{}, {"jobs": "not-a-list"}, {"jobs": 42}])
async def test_admin_scheduler_heartbeat_bad_body(client, bad_body):
    r = await client.post(
        "/v1/admin/scheduler/jobs/heartbeat",
        json=bad_body,
        headers=admin_h(),
    )
    # Empty dict is allowed (interpreted as 0 jobs); explicit non-list rejected.
    if "jobs" in bad_body and not isinstance(bad_body["jobs"], list):
        assert r.status_code == 400
    else:
        assert r.status_code == 200
