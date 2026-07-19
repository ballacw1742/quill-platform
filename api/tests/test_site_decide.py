"""Human-in-the-loop accept/reject decision on an evaluated site.

The AI recommendation is advisory. A human accepts (advance to next phase) or
rejects (do not proceed) a site regardless of verdict.

- reject: records the decision on DataSite; no project/approval created.
- accept: records the decision AND kicks off the Lane-2 advance-to-project flow
  (a pending approval; the project is created on approve).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from tests.conftest import auth_h

SITE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

# A weak/low-scoring site — the human can still accept or reject it.
FAKE_SITE = {
    "site_id": SITE_ID,
    "status": "review",
    "target_workload": "ai_hpc",
    "target_mw": 4800,
    "property": {"address": None, "city": None, "state": "WV", "zip": None,
                 "lat": 37.5965, "lng": -81.9552},
    "scores": {"total_weighted": 50.0},
    "recommendation": {"verdict": "weak", "summary": "Hold for more data.",
                       "next_steps": ["Confirm power"]},
    "documents": [],
}


@pytest.fixture
def fake_datasite(monkeypatch):
    """Patch the DataSite proxy so no real HTTP call happens.

    Records the decide payload so tests can assert what was forwarded.
    """
    from app.routes import sites as sites_module

    calls: dict = {"decide": None}

    async def _fake(method: str, path: str, **kwargs):
        if path == f"/sites/{SITE_ID}" and method == "get":
            return FAKE_SITE
        if path == f"/sites/{SITE_ID}/decide" and method == "post":
            calls["decide"] = kwargs.get("json")
            body = kwargs.get("json") or {}
            return {
                "site_id": SITE_ID,
                "status": "decided",
                "decision": "accepted" if body.get("decision") == "accept" else "rejected",
            }
        raise HTTPException(status_code=404, detail="not found")

    monkeypatch.setattr(sites_module, "_datasite_request", _fake)
    return calls


async def test_decide_requires_auth(client, fake_datasite):
    r = await client.post(f"/v1/sites/{SITE_ID}/decide", json={"decision": "reject"})
    assert r.status_code == 401


async def test_bad_decision_400(client, owner_token, fake_datasite):
    _, tok = owner_token
    r = await client.post(f"/v1/sites/{SITE_ID}/decide", headers=auth_h(tok),
                          json={"decision": "maybe"})
    assert r.status_code == 400


async def test_reject_records_decision_no_project(client, owner_token, fake_datasite):
    _, tok = owner_token
    r = await client.post(f"/v1/sites/{SITE_ID}/decide", headers=auth_h(tok),
                          json={"decision": "reject", "notes": "insufficient power data"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "reject"
    assert body["status"] == "decided"
    # decision forwarded to DataSite with the deciding user + notes
    assert fake_datasite["decide"]["decision"] == "reject"
    assert fake_datasite["decide"]["notes"] == "insufficient power data"
    assert fake_datasite["decide"]["decided_by"]  # email present

    # Reject must NOT create a project.
    r = await client.get("/v1/projects", headers=auth_h(tok))
    assert r.status_code == 200
    assert r.json()["total"] == 0


async def test_accept_weak_site_creates_pending_advance(client, owner_token, fake_datasite):
    _, tok = owner_token
    r = await client.post(f"/v1/sites/{SITE_ID}/decide", headers=auth_h(tok),
                          json={"decision": "accept"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "accept"
    assert fake_datasite["decide"]["decision"] == "accept"
    # accept kicks off the advance flow -> pending approval, no project yet.
    advance = body.get("advance") or {}
    assert advance.get("status") == "pending_approval"

    # No project yet — execute-on-approve.
    r = await client.get("/v1/projects", headers=auth_h(tok))
    assert r.status_code == 200
    assert r.json()["total"] == 0
