"""Phase G.4 — RvtExtractor tests.

Without APS credentials, RvtExtractor returns 'not_configured' with a
friendly workaround message. With credentials + mocked HTTP, the
extractor walks the full APS pipeline (auth → upload → translate →
poll → metadata → quantities) and returns an 'ok' result.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.aps import APSClient
from app.services.drawings import (
    DrawingExtractionResult,
    RvtExtractor,
    detect_kind,
    extract,
)


def test_rvt_kind_detection():
    assert detect_kind("model.rvt") == "rvt"
    assert detect_kind("MODEL.RVT") == "rvt"


def test_rvt_no_creds_returns_not_configured(monkeypatch):
    monkeypatch.delenv("APS_CLIENT_ID", raising=False)
    monkeypatch.delenv("APS_CLIENT_SECRET", raising=False)
    result = RvtExtractor().extract(filename="model.rvt", data=b"\x00" * 32)
    assert isinstance(result, DrawingExtractionResult)
    assert result.kind == "rvt"
    assert result.extraction_status == "failed"
    assert "APS_CLIENT_ID" in result.summary
    assert "IFC" in result.summary  # workaround
    assert result.entities.get("extraction_status_detail") == "not_configured"


def test_rvt_extract_via_public_entry_routes_to_rvt_extractor(monkeypatch):
    monkeypatch.delenv("APS_CLIENT_ID", raising=False)
    monkeypatch.delenv("APS_CLIENT_SECRET", raising=False)
    result = extract(filename="x.rvt", data=b"\x00" * 8)
    assert result.kind == "rvt"
    assert result.entities.get("extraction_status_detail") == "not_configured"


def test_rvt_with_aps_creds_runs_full_pipeline(monkeypatch):
    """End-to-end happy path with all APS HTTP calls mocked."""
    monkeypatch.setenv("APS_CLIENT_ID", "id")
    monkeypatch.setenv("APS_CLIENT_SECRET", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "authentication/v2/token" in url:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if url.endswith("/oss/v2/buckets") and request.method == "POST":
            return httpx.Response(200, json={"bucketKey": "k"})
        if "/objects/" in url and request.method == "PUT":
            return httpx.Response(200, json={
                "objectId": "urn:adsk.objects:os.object:k/model.rvt"
            })
        if url.endswith("/modelderivative/v2/designdata/job"):
            return httpx.Response(200, json={"result": "created"})
        if "/manifest" in url:
            return httpx.Response(200, json={"status": "success"})
        if "/metadata" in url and "/properties" not in url:
            return httpx.Response(200, json={
                "data": {"metadata": [{"guid": "g", "role": "3d"}]}
            })
        if "/properties" in url:
            return httpx.Response(200, json={
                "data": {"collection": [
                    {"objectid": 1, "name": "Wall-1", "properties": {
                        "Dimensions": {"Length": 10.0, "Area": 30.0}
                    }},
                    {"objectid": 2, "name": "Door-1", "properties": {
                        "Dimensions": {"Width": 3.0}
                    }},
                ]}
            })
        return httpx.Response(404, json={"err": f"unexpected {url}"})

    transport = httpx.MockTransport(handler)

    def _http(self):
        return httpx.AsyncClient(transport=transport, timeout=self.timeout_s)

    monkeypatch.setattr(APSClient, "_http", _http)

    result = RvtExtractor().extract(filename="model.rvt", data=b"\x00" * 16)
    assert result.kind == "rvt"
    assert result.extraction_status == "ok"
    assert "APS Model Derivative" in result.summary
    assert len(result.entities.get("elements", [])) == 2
    # Quantities should be rolled up across both elements.
    assert "Dimensions::Length" in result.quantities
    assert result.quantities["Dimensions::Length"] == 10.0
    assert result.quantities["Dimensions::Area"] == 30.0
