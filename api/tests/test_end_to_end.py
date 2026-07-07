"""End-to-end approval lifecycle: create → list → get → decide → execute → audit."""

from __future__ import annotations

from tests.conftest import agent_h, auth_h

SAMPLE = {
    "agent_id": "rfi-triage",
    "agent_version": "0.1.0",
    "workflow": "rfi.classify",
    "lane": 2,
    "priority": "normal",
    "target_system": "procore",
    "agent_confidence": 0.82,
    "payload": {"rfi_id": "RFI-T-1", "category": "MEP"},
    "source_artifacts": [{"kind": "rfi", "ref": "RFI-T-1"}],
    "citations": [{"source_type": "procore_rfi", "source_id": "RFI-T-1"}],
}


async def test_full_lifecycle(client, owner_token):
    user_id, token = owner_token

    # Create
    r = await client.post("/v1/approvals", json=SAMPLE, headers=agent_h())
    assert r.status_code == 201, r.text
    item = r.json()
    aid = item["id"]
    assert item["status"] == "pending"
    assert item["audit_hash"]

    # List
    r = await client.get("/v1/approvals?lane=2", headers=agent_h())
    assert r.status_code == 200
    page = r.json()
    assert page["total"] >= 1

    # Get
    r = await client.get(f"/v1/approvals/{aid}", headers=agent_h())
    assert r.status_code == 200
    assert r.json()["id"] == aid

    # Decide → approve
    r = await client.post(
        f"/v1/approvals/{aid}/decide",
        json={"decision": "approve", "auth_assertion": "dev"},
        headers=auth_h(token),
    )
    assert r.status_code == 200, r.text
    decided = r.json()
    assert decided["status"] in ("executed", "approved")
    assert len(decided["records"]) == 1

    # Audit chain
    r = await client.get(f"/v1/approvals/{aid}/audit", headers=agent_h())
    assert r.status_code == 200
    chain = r.json()
    assert len(chain) >= 2  # created + decided + executed
    types = [e["event_type"] for e in chain]
    assert "approval.created" in types
    assert "approval.executed" in types

    # Verify
    r = await client.get(f"/v1/audit/verify/{aid}")
    assert r.status_code == 200
    assert r.json()["ok"] is True


async def test_reject_path(client, owner_token):
    _, token = owner_token
    r = await client.post("/v1/approvals", json=SAMPLE, headers=agent_h())
    aid = r.json()["id"]

    r = await client.post(
        f"/v1/approvals/{aid}/decide",
        json={"decision": "reject", "rejection_reason": "wrong category"},
        headers=auth_h(token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


async def test_cancel(client):
    r = await client.post("/v1/approvals", json=SAMPLE, headers=agent_h())
    aid = r.json()["id"]

    r = await client.patch(
        f"/v1/approvals/{aid}/cancel", json={"reason": "duplicate"}, headers=agent_h()
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


async def test_agent_secret_required(client):
    r = await client.post("/v1/approvals", json=SAMPLE)  # no header
    assert r.status_code == 401
