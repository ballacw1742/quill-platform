"""Sprint A6 — agent-cloud proposed writes execute-on-approve.

Contract: agent-cloud/APPROVALS.md. The agent secret can only *queue* an
approval item (workflow agentcloud.*); the write itself happens inside the
approvals executor after a human approves, with args re-validated. Terminal
transitions best-effort notify agent-cloud (secret-gated; disabled ⇒ no-op).
"""

from __future__ import annotations

import pytest

from tests.conftest import agent_h, auth_h

TENANT = "test-tenant"


def _approval_body(action: str, args: dict, workflow: str | None = None) -> dict:
    return {
        "agent_id": f"agentcloud:{TENANT}/quill",
        "agent_version": "a6",
        "workflow": workflow or f"agentcloud.{action}",
        "lane": 2,
        "priority": "normal",
        "target_system": "none",
        "payload": {
            "proposed_action": {
                "kind": "agentcloud_write",
                "action": action,
                "args": args,
                "tenant_id": TENANT,
                "agent_id": "quill",
                "session_id": None,
                "proposal_id": "11111111-1111-1111-1111-111111111111",
                "idempotency_key": "sha256:test",
            }
        },
        "agent_reasoning": "test proposal",
    }


async def _make_project(client, tok: str, **overrides) -> dict:
    body = {"name": "AC Test Project", "phase": "site_control", "status": "active"}
    body.update(overrides)
    r = await client.post("/v1/projects", json=body, headers=auth_h(tok))
    assert r.status_code == 201, r.text
    return r.json()


async def _queue_and_approve(client, tok: str, action: str, args: dict) -> dict:
    r = await client.post("/v1/approvals", json=_approval_body(action, args), headers=agent_h())
    assert r.status_code == 201, r.text
    approval_id = r.json()["id"]
    assert r.json()["status"] == "pending"
    r = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "approve"},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_queue_requires_agent_secret(client):
    r = await client.post("/v1/approvals", json=_approval_body("project_update", {}))
    assert r.status_code in (401, 403)


async def test_project_update_executes_on_approve(client, owner_token):
    _, tok = owner_token
    project = await _make_project(client, tok)

    body = await _queue_and_approve(
        client, tok, "project_update", {"project_id": project["id"], "advance_phase": True}
    )
    assert body["status"] == "executed"
    assert body["execution_result"] == "success"
    assert body["external_ref"] == f"project:{project['id']}"

    r = await client.get(f"/v1/projects/{project['id']}", headers=auth_h(tok))
    assert r.json()["phase"] == "permitting"

    # Audit chain carries the agentcloud workflow.
    r = await client.get(f"/v1/approvals/{body['id']}/audit", headers=auth_h(tok))
    events = {e["event_type"]: e for e in r.json()}
    assert "approval.created" in events
    assert "approval.decision.approve" in events
    executed = events["approval.executed"]
    assert executed["payload"]["agentcloud_workflow"] == "agentcloud.project_update"
    assert executed["payload"]["external_ref"] == f"project:{project['id']}"


async def test_project_log_and_milestone(client, owner_token):
    _, tok = owner_token
    project = await _make_project(client, tok)

    body = await _queue_and_approve(
        client,
        tok,
        "project_log_note",
        {"project_id": project["id"], "entry_type": "issue", "text": "Pump failed."},
    )
    assert body["external_ref"].startswith("project_log:")
    r = await client.get(f"/v1/projects/{project['id']}/log", headers=auth_h(tok))
    assert r.json()["items"][0]["text"] == "Pump failed."

    body = await _queue_and_approve(
        client,
        tok,
        "project_milestone_create",
        {"project_id": project["id"], "name": "Energize", "due_date": "2026-09-01"},
    )
    assert body["external_ref"].startswith("milestone:")
    r = await client.get(f"/v1/projects/{project['id']}/milestones", headers=auth_h(tok))
    assert r.json()["items"][0]["name"] == "Energize"


async def test_deal_update_won_upgrades_account(client, owner_token):
    _, tok = owner_token
    r = await client.post(
        "/v1/accounts", json={"name": "ACME", "type": "prospect"}, headers=auth_h(tok)
    )
    account_id = r.json()["id"]
    r = await client.post(
        "/v1/deals",
        json={"account_id": account_id, "name": "Big TPU", "stage": "negotiating"},
        headers=auth_h(tok),
    )
    deal_id = r.json()["id"]

    body = await _queue_and_approve(
        client, tok, "deal_update", {"deal_id": deal_id, "stage": "won", "value_usd": 5000000}
    )
    assert body["external_ref"] == f"deal:{deal_id}"
    r = await client.get(f"/v1/deals/{deal_id}", headers=auth_h(tok))
    assert r.json()["stage"] == "won"
    assert r.json()["value_usd"] == 5000000
    assert r.json()["account"]["type"] == "customer"


async def test_request_update(client, owner_token, session_maker):
    _, tok = owner_token
    from app.models_requests import RequestRecord

    async with session_maker() as s:
        rec = RequestRecord(user_id="u1", message="need an estimate", intent="estimate")
        s.add(rec)
        await s.commit()
        await s.refresh(rec)

    body = await _queue_and_approve(
        client,
        tok,
        "request_update",
        {"request_id": rec.id, "status": "complete", "response": "Done."},
    )
    assert body["external_ref"] == f"request:{rec.id}"
    async with session_maker() as s:
        fresh = await s.get(RequestRecord, rec.id)
        assert fresh.status == "complete"
        assert fresh.response == "Done."


async def test_bad_args_execution_failed_no_write(client, owner_token):
    _, tok = owner_token
    r = await client.post(
        "/v1/approvals",
        json=_approval_body("project_update", {"project_id": "nope", "advance_phase": True}),
        headers=agent_h(),
    )
    approval_id = r.json()["id"]
    r = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "approve"},
        headers=auth_h(tok),
    )
    assert r.status_code == 409  # AgentCloudActionError → ValueError → 409

    r = await client.get(f"/v1/approvals/{approval_id}", headers=auth_h(tok))
    assert r.json()["status"] == "execution_failed"
    r = await client.get(f"/v1/approvals/{approval_id}/audit", headers=auth_h(tok))
    events = [e["event_type"] for e in r.json()]
    assert "approval.execution_failed" in events
    # No project appeared out of thin air.
    r = await client.get("/v1/projects", headers=auth_h(tok))
    assert r.json()["total"] == 0


async def test_malformed_proposed_action_fails(client, owner_token):
    _, tok = owner_token
    body = _approval_body("project_update", {})
    body["payload"] = {"something": "else"}  # no proposed_action
    r = await client.post("/v1/approvals", json=body, headers=agent_h())
    approval_id = r.json()["id"]
    r = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "approve"},
        headers=auth_h(tok),
    )
    assert r.status_code == 409
    r = await client.get(f"/v1/approvals/{approval_id}", headers=auth_h(tok))
    assert r.json()["status"] == "execution_failed"


class _FakeResponse:
    status_code = 200
    text = ""


class _FakeAsyncClient:
    """Captures notify POSTs (module-level list survives client lifecycles)."""

    posts: list[tuple[str, dict, dict]] = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.posts.append((url, json, headers))
        return _FakeResponse()


@pytest.fixture
def notify_capture(monkeypatch):
    from app.config import get_settings
    from app.services import agentcloud_actions

    _FakeAsyncClient.posts = []
    monkeypatch.setattr(agentcloud_actions.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(get_settings(), "AGENTCLOUD_NOTIFY_SECRET", "notify-secret")
    return _FakeAsyncClient.posts


async def test_notify_on_execute(client, owner_token, notify_capture):
    _, tok = owner_token
    project = await _make_project(client, tok)
    await _queue_and_approve(
        client, tok, "project_update", {"project_id": project["id"], "status": "on_hold"}
    )
    assert len(notify_capture) == 1
    url, body, headers = notify_capture[0]
    assert url.endswith("/v1/internal/approvals/notify")
    assert headers["X-Agent-Secret"] == "notify-secret"
    assert body["status"] == "executed"
    assert body["workflow"] == "agentcloud.project_update"
    assert body["tenant_id"] == TENANT
    assert body["external_ref"] == f"project:{project['id']}"


async def test_notify_on_reject_and_cancel(client, owner_token, notify_capture):
    _, tok = owner_token
    r = await client.post(
        "/v1/approvals",
        json=_approval_body("project_update", {"project_id": "x", "advance_phase": True}),
        headers=agent_h(),
    )
    approval_id = r.json()["id"]
    r = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "reject", "rejection_reason": "no"},
        headers=auth_h(tok),
    )
    assert r.status_code == 200
    assert notify_capture[-1][1]["status"] == "rejected"

    r = await client.post(
        "/v1/approvals",
        json=_approval_body("project_update", {"project_id": "y", "advance_phase": True}),
        headers=agent_h(),
    )
    approval_id = r.json()["id"]
    r = await client.patch(f"/v1/approvals/{approval_id}/cancel", headers=agent_h())
    assert r.status_code == 200
    assert notify_capture[-1][1]["status"] == "cancelled"


async def test_notify_failure_is_swallowed(client, owner_token, monkeypatch):
    """A dead agent-cloud must not break approval execution."""
    from app.config import get_settings
    from app.services import agentcloud_actions

    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(agentcloud_actions.httpx, "AsyncClient", _Boom)
    monkeypatch.setattr(get_settings(), "AGENTCLOUD_NOTIFY_SECRET", "notify-secret")

    _, tok = owner_token
    project = await _make_project(client, tok)
    body = await _queue_and_approve(
        client, tok, "project_update", {"project_id": project["id"], "status": "on_hold"}
    )
    assert body["status"] == "executed"


async def test_notify_disabled_when_secret_unset(client, owner_token, monkeypatch):
    from app.config import get_settings
    from app.services import agentcloud_actions

    called = []
    monkeypatch.setattr(
        agentcloud_actions.httpx,
        "AsyncClient",
        lambda *a, **k: called.append(1),
    )
    monkeypatch.setattr(get_settings(), "AGENTCLOUD_NOTIFY_SECRET", "")

    _, tok = owner_token
    project = await _make_project(client, tok)
    body = await _queue_and_approve(
        client, tok, "project_update", {"project_id": project["id"], "status": "on_hold"}
    )
    assert body["status"] == "executed"
    assert called == []
