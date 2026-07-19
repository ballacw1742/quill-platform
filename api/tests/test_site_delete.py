"""DELETE /v1/sites/{id} — delete a rejected site record (proxy to DataSite).

DataSite guards the delete (only rejected sites, 409 otherwise). The Quill
proxy forwards the call and records an audit event.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from tests.conftest import auth_h

SITE_ID = "dddddddd-eeee-ffff-0000-111111111111"


@pytest.fixture
def fake_datasite(monkeypatch):
    from app.routes import sites as sites_module

    calls: dict = {"deleted": None}

    async def _fake(method: str, path: str, **kwargs):
        if path == f"/sites/{SITE_ID}" and method == "delete":
            calls["deleted"] = SITE_ID
            return {"site_id": SITE_ID, "deleted": True, "was_verdict": "rejected"}
        if path == "/sites/blocked-site" and method == "delete":
            # DataSite guard: not rejected → 409
            raise HTTPException(status_code=409, detail="Only a rejected site can be deleted.")
        raise HTTPException(status_code=404, detail="not found")

    monkeypatch.setattr(sites_module, "_datasite_request", _fake)
    return calls


async def test_delete_requires_auth(client, fake_datasite):
    r = await client.delete(f"/v1/sites/{SITE_ID}")
    assert r.status_code == 401


async def test_delete_rejected_site_ok(client, owner_token, fake_datasite):
    _, tok = owner_token
    r = await client.delete(f"/v1/sites/{SITE_ID}", headers=auth_h(tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] is True
    assert body["was_verdict"] == "rejected"
    assert fake_datasite["deleted"] == SITE_ID


async def test_delete_non_rejected_site_409_passthrough(client, owner_token, fake_datasite):
    _, tok = owner_token
    r = await client.delete("/v1/sites/blocked-site", headers=auth_h(tok))
    assert r.status_code == 409
