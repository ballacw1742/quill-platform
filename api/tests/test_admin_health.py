"""Admin/health endpoint sanity."""

from __future__ import annotations

from tests.conftest import admin_h, agent_h


async def test_health_empty(client):
    r = await client.get("/v1/admin/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["db"] == "ok"
    assert body["queue_depth_pending"] == 0
    assert body["audit_chain"] == "empty"


async def test_health_after_create(client):
    sample = {
        "agent_id": "rfi-triage",
        "workflow": "rfi.classify",
        "lane": 2,
        "agent_confidence": 0.7,
        "payload": {"rfi_id": "RFI-H-1"},
        "source_artifacts": [{"kind": "rfi", "ref": "RFI-H-1"}],
        "citations": [{"source_type": "procore_rfi", "source_id": "RFI-H-1"}],
    }
    await client.post("/v1/approvals", json=sample, headers=agent_h())

    r = await client.get("/v1/admin/health")
    body = r.json()
    assert body["queue_depth_pending"] == 1
    assert body["audit_chain"] == "ok"
    assert body["audit_chain_length"] >= 1


async def test_admin_audit_verify_requires_header(client):
    r = await client.post("/v1/admin/audit_verify")
    assert r.status_code == 401

    r = await client.post("/v1/admin/audit_verify", headers=admin_h())
    assert r.status_code == 200
    assert r.json()["ok"] is True
