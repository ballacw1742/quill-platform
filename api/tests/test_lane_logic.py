"""Lane logic: Lane 3 needs two approvers; Lane 1 auto-executes."""

from __future__ import annotations

from tests.conftest import agent_h, auth_h


def lane_payload(lane: int):
    return {
        "agent_id": "co-estimator",
        "workflow": "co.estimate",
        "lane": lane,
        "agent_confidence": 0.8,
        "payload": {"co_id": f"CO-{lane}"},
        "source_artifacts": [{"kind": "rfi", "ref": "x"}],
        "citations": [{"source_type": "procore_rfi", "source_id": "x"}],
    }


async def test_lane3_requires_two(client, owner_token, partner_token):
    _, owner_t = owner_token
    _, partner_t = partner_token

    r = await client.post("/v1/approvals", json=lane_payload(3), headers=agent_h())
    assert r.status_code == 201
    aid = r.json()["id"]
    assert r.json()["lane"] == 3
    assert set(r.json()["required_approvers"]) == {"owner", "partner"}

    # Owner approves first → still pending
    r = await client.post(
        f"/v1/approvals/{aid}/decide",
        json={"decision": "approve"},
        headers=auth_h(owner_t),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending"

    # Partner approves → approved + executed
    r = await client.post(
        f"/v1/approvals/{aid}/decide",
        json={"decision": "approve"},
        headers=auth_h(partner_t),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in ("executed", "approved")
    assert len(body["records"]) == 2


async def test_lane1_auto_executes(client):
    r = await client.post("/v1/approvals", json=lane_payload(1), headers=agent_h())
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "executed"
    assert body["execution_result"] == "dry_run"


async def test_double_sign_blocked(client, owner_token):
    _, owner_t = owner_token
    r = await client.post("/v1/approvals", json=lane_payload(3), headers=agent_h())
    aid = r.json()["id"]

    r = await client.post(
        f"/v1/approvals/{aid}/decide",
        json={"decision": "approve"},
        headers=auth_h(owner_t),
    )
    assert r.status_code == 200

    r2 = await client.post(
        f"/v1/approvals/{aid}/decide",
        json={"decision": "approve"},
        headers=auth_h(owner_t),
    )
    assert r2.status_code == 409
