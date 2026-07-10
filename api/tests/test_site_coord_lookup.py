"""
Tests for coordinate-based site lookup (feat-site-coord-lookup).

Covers:
- evaluate_site: address-only OK
- evaluate_site: coords-only OK
- evaluate_site: both address+coords OK (coords forwarded)
- evaluate_site: neither address nor coords → 400
- evaluate_site: lat without lon → 400 (partial coords treated as neither)
- evaluate_site: coords forwarded to DataSite payload
- create_site: address-only OK
- create_site: coords-only OK
- create_site: both OK
- create_site: neither → 400

All DataSite HTTP calls are mocked — no live calls.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from tests.conftest import auth_h


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_SITE_RESPONSE = {
    "site_id": "test-site-001",
    "status": "intake",
    "property": {"address": None, "lat": 39.9612, "lng": -82.9988},
}

FAKE_EVAL_RESPONSE = {
    "site_id": "eval-001",
    "status": "complete",
    "verdict": "conditional",
    "total_score": 72.5,
    "summary": "Promising site, needs power confirmation.",
}


@pytest.fixture
def mock_datasite_create(monkeypatch):
    """Patch _datasite_request to return a fake created site."""
    from app.routes import sites as sites_module

    async def _fake(method: str, path: str, **kwargs):
        if method == "post" and path == "/sites":
            return FAKE_SITE_RESPONSE
        raise HTTPException(status_code=404, detail="not found")

    monkeypatch.setattr(sites_module, "_datasite_request", _fake)
    return _fake


@pytest.fixture
def mock_datasite_eval(monkeypatch):
    """Patch the httpx.AsyncClient used by evaluate_site to return a fake eval."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = FAKE_EVAL_RESPONSE

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            # Capture what was actually sent for assertion
            self._last_kwargs = kwargs
            return mock_resp

    mock_client_instance = MockAsyncClient()

    import httpx as httpx_module
    from app.routes import sites as sites_module

    def fake_client(**kwargs):
        return mock_client_instance

    monkeypatch.setattr(sites_module.httpx, "AsyncClient", fake_client)
    return mock_client_instance


# ---------------------------------------------------------------------------
# create_site validation tests
# ---------------------------------------------------------------------------


async def test_create_site_requires_auth(client):
    """create_site requires authentication."""
    r = await client.post("/v1/sites", json={"address": "100 Main St"})
    assert r.status_code == 401


async def test_create_site_address_only_ok(client, owner_token, mock_datasite_create):
    """create_site with address-only body is accepted and proxied to DataSite."""
    _, tok = owner_token
    body = {
        "address": "100 Tech Park Dr",
        "city": "Columbus",
        "state": "OH",
        "zip": "43215",
        "target_workload": "ai_hpc",
    }
    r = await client.post("/v1/sites", json=body, headers=auth_h(tok))
    assert r.status_code == 200, r.text
    data = r.json()
    assert "site_id" in data


async def test_create_site_coords_only_ok(client, owner_token, mock_datasite_create):
    """create_site with coordinates only (no address) is accepted."""
    _, tok = owner_token
    body = {
        "latitude": 39.9612,
        "longitude": -82.9988,
        "target_workload": "ai_hpc",
    }
    r = await client.post("/v1/sites", json=body, headers=auth_h(tok))
    assert r.status_code == 200, r.text
    data = r.json()
    assert "site_id" in data


async def test_create_site_both_address_and_coords_ok(client, owner_token, mock_datasite_create):
    """create_site with both address and coordinates is accepted."""
    _, tok = owner_token
    body = {
        "address": "100 Tech Park Dr",
        "city": "Columbus",
        "state": "OH",
        "zip": "43215",
        "latitude": 39.9612,
        "longitude": -82.9988,
        "target_workload": "ai_hpc",
    }
    r = await client.post("/v1/sites", json=body, headers=auth_h(tok))
    assert r.status_code == 200, r.text


async def test_create_site_neither_address_nor_coords_returns_400(client, owner_token, mock_datasite_create):
    """create_site with neither address nor coords returns 400."""
    _, tok = owner_token
    body = {
        "target_workload": "ai_hpc",
        "lead_source": "broker",
    }
    r = await client.post("/v1/sites", json=body, headers=auth_h(tok))
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "address" in detail.lower() or "latitude" in detail.lower()


async def test_create_site_empty_address_without_coords_returns_400(client, owner_token, mock_datasite_create):
    """create_site with empty/whitespace address and no coords returns 400."""
    _, tok = owner_token
    body = {
        "address": "   ",
        "target_workload": "ai_hpc",
    }
    r = await client.post("/v1/sites", json=body, headers=auth_h(tok))
    assert r.status_code == 400, r.text


async def test_create_site_only_latitude_without_longitude_returns_400(client, owner_token, mock_datasite_create):
    """create_site with only latitude (no longitude) returns 400 (treated as no coords)."""
    _, tok = owner_token
    body = {
        "latitude": 39.9612,
        "target_workload": "ai_hpc",
    }
    r = await client.post("/v1/sites", json=body, headers=auth_h(tok))
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# evaluate_site validation tests
# ---------------------------------------------------------------------------


async def test_evaluate_site_requires_auth(client):
    """evaluate_site requires authentication."""
    r = await client.post("/v1/sites/evaluate", data={"address": "100 Main St"})
    assert r.status_code == 401


async def test_evaluate_site_address_only_ok(client, owner_token, mock_datasite_eval):
    """evaluate_site with address-only is accepted."""
    _, tok = owner_token
    r = await client.post(
        "/v1/sites/evaluate",
        data={"address": "100 Tech Park Dr, Columbus OH 43215", "workload": "ai_hpc"},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["site_id"] == "eval-001"


async def test_evaluate_site_coords_only_ok(client, owner_token, mock_datasite_eval):
    """evaluate_site with coordinates only is accepted."""
    _, tok = owner_token
    r = await client.post(
        "/v1/sites/evaluate",
        data={"latitude": "39.9612", "longitude": "-82.9988", "workload": "ai_hpc"},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["site_id"] == "eval-001"


async def test_evaluate_site_both_ok(client, owner_token, mock_datasite_eval):
    """evaluate_site with both address and coords is accepted."""
    _, tok = owner_token
    r = await client.post(
        "/v1/sites/evaluate",
        data={
            "address": "100 Tech Park Dr",
            "latitude": "39.9612",
            "longitude": "-82.9988",
            "workload": "ai_hpc",
        },
        headers=auth_h(tok),
    )
    assert r.status_code == 200, r.text


async def test_evaluate_site_neither_returns_400(client, owner_token, mock_datasite_eval):
    """evaluate_site with neither address nor coords returns 400."""
    _, tok = owner_token
    r = await client.post(
        "/v1/sites/evaluate",
        data={"workload": "ai_hpc"},
        headers=auth_h(tok),
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "address" in detail.lower() or "latitude" in detail.lower()


async def test_evaluate_site_empty_address_without_coords_returns_400(client, owner_token, mock_datasite_eval):
    """evaluate_site with empty address string and no coords returns 400."""
    _, tok = owner_token
    r = await client.post(
        "/v1/sites/evaluate",
        data={"address": "", "workload": "ai_hpc"},
        headers=auth_h(tok),
    )
    assert r.status_code == 400, r.text


async def test_evaluate_site_coords_forwarded_in_payload(client, owner_token, mock_datasite_eval):
    """evaluate_site forwards latitude and longitude to the DataSite payload."""
    _, tok = owner_token
    r = await client.post(
        "/v1/sites/evaluate",
        data={
            "latitude": "39.9612",
            "longitude": "-82.9988",
            "workload": "ai_hpc",
        },
        headers=auth_h(tok),
    )
    assert r.status_code == 200, r.text
    # Check that coords were in the forwarded data
    last_call = mock_datasite_eval._last_kwargs
    forwarded_data = last_call.get("data", {})
    assert "latitude" in forwarded_data, f"latitude not forwarded; got keys: {list(forwarded_data.keys())}"
    assert "longitude" in forwarded_data, f"longitude not forwarded; got keys: {list(forwarded_data.keys())}"
    assert forwarded_data["latitude"] == "39.9612"
    assert forwarded_data["longitude"] == "-82.9988"


async def test_evaluate_site_address_forwarded_in_payload(client, owner_token, mock_datasite_eval):
    """evaluate_site forwards address to the DataSite payload."""
    _, tok = owner_token
    r = await client.post(
        "/v1/sites/evaluate",
        data={"address": "100 Tech Park Dr, Columbus OH", "workload": "ai_hpc"},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, r.text
    last_call = mock_datasite_eval._last_kwargs
    forwarded_data = last_call.get("data", {})
    assert "address" in forwarded_data
    assert forwarded_data["address"] == "100 Tech Park Dr, Columbus OH"
