"""Phase G.4 — APSClient tests (mocked HTTP).

We exercise the client end-to-end with httpx mocking so we don't depend
on real Autodesk credentials. Tests cover:
  - is_available toggles cleanly on env vars
  - authenticate caches the token until expiry
  - upload sends to the right URL and returns a valid base64url URN
  - start_translation posts the right job body
  - poll_translation handles success / failure / pending → success
  - get_metadata + get_quantities parse the APS response shapes
"""

from __future__ import annotations

import base64
import time

import httpx
import pytest

from app.services.aps import (
    APS_BASE,
    APSClient,
    APSToken,
    DEFAULT_BUCKET_PREFIX,
    _b64url_no_pad,
)


# ---------------------------------------------------------------------------
# Helpers — install a MockTransport on httpx.AsyncClient
# ---------------------------------------------------------------------------
def _install_mock(monkeypatch, handler):
    """Patch APSClient._http to use a MockTransport with `handler`."""
    transport = httpx.MockTransport(handler)

    def _http(self):
        return httpx.AsyncClient(transport=transport, timeout=self.timeout_s)

    monkeypatch.setattr(APSClient, "_http", _http)


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------
def test_is_available_false_without_creds(monkeypatch):
    monkeypatch.delenv("APS_CLIENT_ID", raising=False)
    monkeypatch.delenv("APS_CLIENT_SECRET", raising=False)
    c = APSClient()
    assert c.is_available is False


def test_is_available_true_with_creds(monkeypatch):
    monkeypatch.setenv("APS_CLIENT_ID", "abc")
    monkeypatch.setenv("APS_CLIENT_SECRET", "shh")
    c = APSClient()
    assert c.is_available is True


def test_default_bucket_key_uses_client_id(monkeypatch):
    monkeypatch.setenv("APS_CLIENT_ID", "TestClient123!@#")
    c = APSClient()
    assert c.bucket_key.startswith(DEFAULT_BUCKET_PREFIX)
    # alnum-filtered, lowercased
    assert "testclient123" in c.bucket_key


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------
def test_b64url_no_pad():
    raw = "urn:adsk.objects:os.object:my-bucket/model.rvt"
    out = _b64url_no_pad(raw)
    # Round-trip: decode and check
    assert "=" not in out
    pad = "=" * (-len(out) % 4)
    assert base64.urlsafe_b64decode(out + pad).decode("utf-8") == raw


@pytest.mark.asyncio
async def test_authenticate_caches_token(monkeypatch):
    monkeypatch.setenv("APS_CLIENT_ID", "id")
    monkeypatch.setenv("APS_CLIENT_SECRET", "secret")

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "authentication/v2/token" in str(request.url):
            call_count["n"] += 1
            return httpx.Response(
                200, json={"access_token": "tok-xyz", "expires_in": 3600}
            )
        return httpx.Response(404)

    _install_mock(monkeypatch, handler)
    c = APSClient()
    t1 = await c.authenticate()
    t2 = await c.authenticate()
    assert t1 == t2 == "tok-xyz"
    # Second call should reuse the cached token (no extra HTTP call)
    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_authenticate_raises_on_4xx(monkeypatch):
    monkeypatch.setenv("APS_CLIENT_ID", "id")
    monkeypatch.setenv("APS_CLIENT_SECRET", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"developerMessage": "bad creds"})

    _install_mock(monkeypatch, handler)
    c = APSClient()
    with pytest.raises(RuntimeError, match="APS auth failed"):
        await c.authenticate()


@pytest.mark.asyncio
async def test_authenticate_no_creds_raises(monkeypatch):
    monkeypatch.delenv("APS_CLIENT_ID", raising=False)
    monkeypatch.delenv("APS_CLIENT_SECRET", raising=False)
    c = APSClient()
    with pytest.raises(RuntimeError, match="APS not configured"):
        await c.authenticate()


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_returns_valid_urn(monkeypatch):
    monkeypatch.setenv("APS_CLIENT_ID", "id")
    monkeypatch.setenv("APS_CLIENT_SECRET", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "authentication/v2/token" in url:
            return httpx.Response(
                200, json={"access_token": "t", "expires_in": 3600}
            )
        if url.endswith("/oss/v2/buckets") and request.method == "POST":
            return httpx.Response(200, json={"bucketKey": "x"})
        if "/objects/" in url and request.method == "PUT":
            object_id = (
                "urn:adsk.objects:os.object:my-bucket/model.rvt"
            )
            return httpx.Response(200, json={"objectId": object_id})
        return httpx.Response(404)

    _install_mock(monkeypatch, handler)
    c = APSClient()
    urn = await c.upload(b"\x00" * 16, "model.rvt")
    # URN should be base64url-encoded (no padding)
    assert "=" not in urn
    decoded = base64.urlsafe_b64decode(urn + "=" * (-len(urn) % 4))
    assert decoded.startswith(b"urn:adsk.objects:os.object:")


@pytest.mark.asyncio
async def test_upload_handles_existing_bucket_409(monkeypatch):
    monkeypatch.setenv("APS_CLIENT_ID", "id")
    monkeypatch.setenv("APS_CLIENT_SECRET", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "authentication/v2/token" in url:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if url.endswith("/oss/v2/buckets"):
            return httpx.Response(409, json={"reason": "Bucket already exists"})
        if "/objects/" in url and request.method == "PUT":
            return httpx.Response(
                200, json={"objectId": "urn:adsk.objects:os.object:b/model.rvt"}
            )
        return httpx.Response(404)

    _install_mock(monkeypatch, handler)
    c = APSClient()
    urn = await c.upload(b"\x00", "model.rvt")
    assert urn  # No exception


# ---------------------------------------------------------------------------
# start_translation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_start_translation_posts_job(monkeypatch):
    monkeypatch.setenv("APS_CLIENT_ID", "id")
    monkeypatch.setenv("APS_CLIENT_SECRET", "secret")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "authentication/v2/token" in url:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if url.endswith("/modelderivative/v2/designdata/job"):
            captured["body"] = request.content
            return httpx.Response(200, json={"result": "created", "urn": "abc"})
        return httpx.Response(404)

    _install_mock(monkeypatch, handler)
    c = APSClient()
    out = await c.start_translation("dXJuOmFi")
    assert out["result"] == "created"
    # The body should reference svf2 + 2d/3d views
    assert b"svf2" in captured["body"]
    assert b"3d" in captured["body"]


# ---------------------------------------------------------------------------
# poll_translation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_poll_translation_succeeds_after_pending(monkeypatch):
    monkeypatch.setenv("APS_CLIENT_ID", "id")
    monkeypatch.setenv("APS_CLIENT_SECRET", "secret")
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "authentication/v2/token" in url:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if "/manifest" in url:
            state["calls"] += 1
            if state["calls"] == 1:
                return httpx.Response(200, json={"status": "inprogress"})
            return httpx.Response(200, json={"status": "success"})
        return httpx.Response(404)

    _install_mock(monkeypatch, handler)
    c = APSClient()
    status = await c.poll_translation("dXJuOmFi", timeout_s=10.0, interval_s=0.01)
    assert status == "success"
    assert state["calls"] >= 2


@pytest.mark.asyncio
async def test_poll_translation_raises_on_failure(monkeypatch):
    monkeypatch.setenv("APS_CLIENT_ID", "id")
    monkeypatch.setenv("APS_CLIENT_SECRET", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "authentication/v2/token" in url:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if "/manifest" in url:
            return httpx.Response(200, json={"status": "failed"})
        return httpx.Response(404)

    _install_mock(monkeypatch, handler)
    c = APSClient()
    with pytest.raises(RuntimeError, match="failed"):
        await c.poll_translation("dXJuOmFi", timeout_s=2.0, interval_s=0.01)


@pytest.mark.asyncio
async def test_poll_translation_times_out(monkeypatch):
    monkeypatch.setenv("APS_CLIENT_ID", "id")
    monkeypatch.setenv("APS_CLIENT_SECRET", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "authentication/v2/token" in url:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if "/manifest" in url:
            return httpx.Response(200, json={"status": "inprogress"})
        return httpx.Response(404)

    _install_mock(monkeypatch, handler)
    c = APSClient()
    with pytest.raises(TimeoutError):
        await c.poll_translation("dXJuOmFi", timeout_s=0.05, interval_s=0.01)


# ---------------------------------------------------------------------------
# get_metadata + get_quantities
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_metadata_picks_3d_view_and_returns_elements(monkeypatch):
    monkeypatch.setenv("APS_CLIENT_ID", "id")
    monkeypatch.setenv("APS_CLIENT_SECRET", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "authentication/v2/token" in url:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if "/metadata" in url and "/properties" not in url:
            return httpx.Response(200, json={
                "data": {"metadata": [
                    {"guid": "g-2d", "name": "Floor Plan", "role": "2d"},
                    {"guid": "g-3d", "name": "{3D}", "role": "3d"},
                ]}
            })
        if "/properties" in url:
            assert "g-3d" in url  # we picked the 3D view
            return httpx.Response(200, json={
                "data": {"collection": [
                    {"objectid": 1, "name": "Wall-1",
                     "properties": {"Dimensions": {"Length": 12.5, "Area": 30.0}}},
                    {"objectid": 2, "name": "Wall-2",
                     "properties": {"Dimensions": {"Length": 8.0, "Area": 20.0}}},
                ]}
            })
        return httpx.Response(404)

    _install_mock(monkeypatch, handler)
    c = APSClient()
    meta = await c.get_metadata("dXJuOmFi")
    assert len(meta["views"]) == 2
    assert len(meta["elements"]) == 2
    assert meta["elements"][0]["name"] == "Wall-1"


@pytest.mark.asyncio
async def test_get_quantities_rolls_up_numeric_props(monkeypatch):
    monkeypatch.setenv("APS_CLIENT_ID", "id")
    monkeypatch.setenv("APS_CLIENT_SECRET", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "authentication/v2/token" in url:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if "/metadata" in url and "/properties" not in url:
            return httpx.Response(200, json={
                "data": {"metadata": [{"guid": "g", "role": "3d"}]}
            })
        if "/properties" in url:
            return httpx.Response(200, json={
                "data": {"collection": [
                    {"objectid": 1, "properties": {
                        "Dimensions": {"Length": 10.0, "Area": 30.0}}},
                    {"objectid": 2, "properties": {
                        "Dimensions": {"Length": 5.0, "Area": 20.0}}},
                ]}
            })
        return httpx.Response(404)

    _install_mock(monkeypatch, handler)
    c = APSClient()
    q = await c.get_quantities("dXJuOmFi")
    assert q["Dimensions::Length"] == 15.0
    assert q["Dimensions::Area"] == 50.0


# ---------------------------------------------------------------------------
# Token freshness
# ---------------------------------------------------------------------------
def test_apstoken_is_expired_safety_margin():
    fresh = APSToken(access_token="t", expires_at=time.time() + 60)
    assert fresh.is_expired is False
    near_expiry = APSToken(access_token="t", expires_at=time.time() + 10)
    # 30s safety margin → tokens within 30s of expiry are considered expired
    assert near_expiry.is_expired is True
