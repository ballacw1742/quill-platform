"""PATCH /v1/sites/{id} — amend editable site inputs (proxy to DataSite).

DataSite guards rejected sites (read-only, 409). The Quill proxy forwards the
patch and records an audit event.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from tests.conftest import auth_h

SITE_ID = "99999999-8888-7777-6666-555555555555"


@pytest.fixture
def fake_datasite(monkeypatch):
    from app.routes import sites as sites_module

    calls: dict = {"patch": None}

    async def _fake(method: str, path: str, **kwargs):
        if path == f"/sites/{SITE_ID}" and method == "patch":
            calls["patch"] = kwargs.get("json")
            return {
                "site_id": SITE_ID,
                "status": "review",
                "changed": list((kwargs.get("json") or {}).keys()),
                "property": {"acres": 250},
                "target_workload": "hyperscale",
                "target_mw": 300,
                "message": "Inputs updated. Re-run the evaluation to re-score.",
            }
        if path == "/sites/rejected-site" and method == "patch":
            raise HTTPException(status_code=409, detail="A rejected site is read-only.")
        raise HTTPException(status_code=404, detail="not found")

    monkeypatch.setattr(sites_module, "_datasite_request", _fake)
    return calls


async def test_update_requires_auth(client, fake_datasite):
    r = await client.patch(f"/v1/sites/{SITE_ID}", json={"acres": 250})
    assert r.status_code == 401


async def test_update_forwards_patch(client, owner_token, fake_datasite):
    _, tok = owner_token
    r = await client.patch(
        f"/v1/sites/{SITE_ID}",
        headers=auth_h(tok),
        json={"acres": 250, "target_workload": "hyperscale", "target_mw": 300},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "acres" in body["changed"]
    assert fake_datasite["patch"]["acres"] == 250
    assert fake_datasite["patch"]["target_workload"] == "hyperscale"


async def test_update_rejected_site_409_passthrough(client, owner_token, fake_datasite):
    _, tok = owner_token
    r = await client.patch("/v1/sites/rejected-site", headers=auth_h(tok), json={"acres": 1})
    assert r.status_code == 409
