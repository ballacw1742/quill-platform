"""Sprint 5.5 (G7) — approval.created broadcast carries lane/workflow/priority.

The Telegram bot's notifier.classify_event renders "New Lane {lane} approval
… {workflow}" straight from the WS event. Before this fix the API published
only {type,id,status}, so pings showed "Lane 0" / "?" against prod. Additive
fields only — existing consumers (web/lib/websocket.ts) read type/id/status.
"""

from __future__ import annotations

import pytest
from app.services.realtime import broadcaster
from tests.conftest import agent_h


@pytest.mark.asyncio
async def test_approval_created_event_is_push_renderable(client, monkeypatch):
    published: list[dict] = []

    async def capture(event: dict) -> None:
        published.append(event)

    monkeypatch.setattr(broadcaster, "publish", capture)

    r = await client.post(
        "/v1/approvals",
        json={
            "agent_id": "rfi-triage",
            "workflow": "rfi.classify",
            "lane": 2,
            "priority": "normal",
            "agent_confidence": 0.8,
            "payload": {"rfi_id": "RFI-1", "safety_critical": True},
            "source_artifacts": [{"kind": "rfi", "ref": "x"}],
            "citations": [{"source_type": "procore_rfi", "source_id": "x"}],
        },
        headers=agent_h(),
    )
    assert r.status_code == 201, r.text

    created = [e for e in published if e.get("type") == "approval.created"]
    assert len(created) == 1
    ev = created[0]
    assert ev["id"] == r.json()["id"]
    assert ev["status"] == "pending"
    assert ev["lane"] == 2
    assert ev["workflow"] == "rfi.classify"
    assert ev["priority"] == "normal"
    assert ev["agent_id"] == "rfi-triage"
    assert ev["payload"] == {"safety_critical": True, "critical_path": False}

    # The bot's classifier must now produce a correctly-labelled Lane 2 ping.
    import pathlib
    import sys

    bot_dir = pathlib.Path(__file__).resolve().parents[2] / "telegram-bot"
    sys.path.insert(0, str(bot_dir))
    try:
        from quill_bot.notifier import classify_event

        notif = classify_event(ev)
        assert notif is not None
        assert "Lane 2" in notif.text
        assert "rfi.classify" in notif.text
        assert notif.silent is False  # safety_critical forces a loud push
    finally:
        sys.path.remove(str(bot_dir))
