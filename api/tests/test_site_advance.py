"""Sprint 2 — site → project advance is Lane-2 gated (execute-on-approve)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from tests.conftest import auth_h

SITE_ID = "11111111-2222-3333-4444-555555555555"

FAKE_SITE = {
    "site_id": SITE_ID,
    "status": "decided",
    "target_workload": "ai_hpc",
    "target_mw": 100,
    "property": {"address": "123 Adams Fork Rd", "city": "Mingo", "state": "WV", "zip": "25661"},
    "scores": {"total_weighted": 78.5},
    "recommendation": {
        "verdict": "strong_recommend",
        "summary": "Strong site.",
        "next_steps": ["Secure land option", "Utility LOI"],
    },
    "documents": [],
}


@pytest.fixture
def fake_datasite(monkeypatch):
    """Patch the DataSite proxy so no real HTTP call happens."""
    from app.routes import sites as sites_module

    async def _fake(method: str, path: str, **kwargs):
        if path == f"/sites/{SITE_ID}":
            return FAKE_SITE
        raise HTTPException(status_code=404, detail="site not found")

    monkeypatch.setattr(sites_module, "_datasite_request", _fake)
    return _fake


async def test_advance_requires_auth(client, fake_datasite):
    r = await client.post(f"/v1/sites/{SITE_ID}/advance")
    assert r.status_code == 401


async def test_advance_unknown_site_404(client, owner_token, fake_datasite):
    _, tok = owner_token
    r = await client.post("/v1/sites/does-not-exist/advance", headers=auth_h(tok))
    assert r.status_code == 404


async def test_advance_creates_approval_not_project(client, owner_token, fake_datasite):
    _, tok = owner_token

    r = await client.post(f"/v1/sites/{SITE_ID}/advance", headers=auth_h(tok))
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "pending_approval"
    approval_id = body["approval_id"]
    assert body["project"]["site_id"] == SITE_ID
    assert body["project"]["site_score"] == 78.5
    assert body["project"]["site_verdict"] == "strong_recommend"
    assert "123 Adams Fork Rd" in body["project"]["address"]

    # No project yet — execute-on-approve.
    r = await client.get("/v1/projects", headers=auth_h(tok))
    assert r.status_code == 200
    assert r.json()["total"] == 0

    # Approval is pending in the queue, lane 2.
    r = await client.get(f"/v1/approvals/{approval_id}")
    assert r.status_code == 200
    item = r.json()
    assert item["status"] == "pending"
    assert item["lane"] == 2
    assert item["workflow"] == "site_advance.create_project"

    # Advance status reflects the pending approval.
    r = await client.get(f"/v1/sites/{SITE_ID}/advance", headers=auth_h(tok))
    assert r.json() == {
        "site_id": SITE_ID,
        "status": "pending_approval",
        "approval_id": approval_id,
    }

    # Idempotent: second advance returns the same pending approval.
    r = await client.post(f"/v1/sites/{SITE_ID}/advance", headers=auth_h(tok))
    assert r.status_code == 202
    assert r.json()["approval_id"] == approval_id


async def test_approve_creates_project_with_site_data(client, owner_token, fake_datasite):
    user_id, tok = owner_token

    r = await client.post(f"/v1/sites/{SITE_ID}/advance", headers=auth_h(tok))
    approval_id = r.json()["approval_id"]

    # Approve → executes → project created.
    r = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "approve"},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "executed"
    assert body["execution_result"] == "success"
    assert body["external_ref"].startswith("project:")
    project_id = body["external_ref"].split(":", 1)[1]

    r = await client.get(f"/v1/projects/{project_id}", headers=auth_h(tok))
    assert r.status_code == 200, r.text
    proj = r.json()
    assert proj["site_id"] == SITE_ID
    assert proj["site_score"] == 78.5
    assert proj["site_verdict"] == "strong_recommend"
    assert proj["workload_type"] == "ai_hpc"
    assert proj["phase"] == "site_control"
    assert proj["user_id"] == user_id
    assert "123 Adams Fork Rd" in proj["address"]

    # Audit chain: created → decision → executed (with project_id).
    r = await client.get(f"/v1/approvals/{approval_id}/audit")
    events = [e["event_type"] for e in r.json()]
    assert "approval.created" in events
    assert "approval.decision.approve" in events
    assert "approval.executed" in events
    executed = [e for e in r.json() if e["event_type"] == "approval.executed"][0]
    assert executed["payload"]["project_id"] == project_id
    assert executed["payload"]["site_id"] == SITE_ID

    # Advance status now reports advanced.
    r = await client.get(f"/v1/sites/{SITE_ID}/advance", headers=auth_h(tok))
    assert r.json()["status"] == "advanced"
    assert r.json()["project_id"] == project_id

    # Re-advance after the project exists → 409.
    r = await client.post(f"/v1/sites/{SITE_ID}/advance", headers=auth_h(tok))
    assert r.status_code == 409


async def test_reject_does_not_create_project(client, owner_token, fake_datasite):
    _, tok = owner_token
    r = await client.post(f"/v1/sites/{SITE_ID}/advance", headers=auth_h(tok))
    approval_id = r.json()["approval_id"]

    r = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "reject", "rejection_reason": "not ready"},
        headers=auth_h(tok),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"

    r = await client.get("/v1/projects", headers=auth_h(tok))
    assert r.json()["total"] == 0

    r = await client.get(f"/v1/sites/{SITE_ID}/advance", headers=auth_h(tok))
    assert r.json()["status"] == "none"
