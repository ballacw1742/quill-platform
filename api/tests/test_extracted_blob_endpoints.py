"""Sprint 4 — extracted-blob HTTP endpoints for remote dispatcher daemons.

Covers:
- GET /v1/estimates/{upload_id}/extracted/{filename}
- GET /v1/contracts/{upload_id}/extracted/{filename}

These exist so the dispatcher daemons (which may run on a different host
than the API — e.g. a Mac Studio pointed at Cloud Run) can read the
API-local extraction blobs over HTTP.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.services.contracts import service as contracts_service
from app.services.estimates import service as estimates_service
from tests.conftest import agent_h, auth_h

async def _settle_background_extraction(
    client, path: str, headers: dict, done_statuses: tuple[str, ...]
) -> None:
    """Let the upload's background extraction task finish before the test
    writes its own blobs (avoids the extractor overwriting them)."""
    for _ in range(200):
        r = await client.get(path, headers=headers)
        if r.status_code == 200 and r.json().get("status") in done_statuses:
            return
        await asyncio.sleep(0.01)


_PDF = (
    b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
    b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >> endobj\n"
    b"xref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000060 00000 n\n0000000110 00000 n\n"
    b"trailer << /Size 4 /Root 1 0 R >>\nstartxref\n160\n%%EOF\n"
)


# ---------------------------------------------------------------------------
# Service-level readers
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_estimates_read_extracted_artifact_roundtrip(
    session_maker, tmp_path, monkeypatch
):
    monkeypatch.setenv("ESTIMATES_BLOB_PATH", str(tmp_path / "blobs"))
    async with session_maker() as s:
        est = await estimates_service.upload(
            s,
            files=[{"filename": "plan.pdf", "size_bytes": len(_PDF), "content": _PDF}],
            project_label="smoke",
        )
    # Simulate what _run_extraction_async writes.
    from app.services.estimates import _extracted_key, _write_blob

    artifact = {"filename": "plan.pdf", "kind": "pdf", "summary": "1 page"}
    _write_blob(
        _extracted_key(est.upload_id, "plan.pdf.json"),
        json.dumps(artifact).encode("utf-8"),
    )

    raw = estimates_service.read_extracted_artifact(est.upload_id, "plan.pdf")
    assert raw is not None
    assert json.loads(raw) == artifact

    assert estimates_service.read_extracted_artifact(est.upload_id, "nope.pdf") is None


@pytest.mark.asyncio
async def test_contracts_read_extracted_text_roundtrip(
    session_maker, tmp_path, monkeypatch
):
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))
    async with session_maker() as s:
        c = await contracts_service.upload(
            s,
            files=[{"filename": "sub.pdf", "size_bytes": len(_PDF), "content": _PDF}],
            project_label="smoke",
        )
    from app.services.contracts import _extracted_key, _safe_name, _write_blob

    _write_blob(
        _extracted_key(c.upload_id, f"{_safe_name('sub.pdf')}.txt"),
        "FULL CONTRACT TEXT" .encode("utf-8"),
    )

    assert contracts_service.read_extracted_text(c.upload_id, "sub.pdf") == "FULL CONTRACT TEXT"
    assert contracts_service.read_extracted_text(c.upload_id, "nope.pdf") is None


# ---------------------------------------------------------------------------
# Route-level: estimates
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_estimates_extracted_route(client, owner_token, tmp_path, monkeypatch):
    _, token = owner_token
    monkeypatch.setenv("ESTIMATES_BLOB_PATH", str(tmp_path / "blobs"))

    resp = await client.post(
        "/v1/estimates/upload",
        files={"files": ("plan.pdf", _PDF, "application/pdf")},
        data={"project_label": "smoke"},
        headers=auth_h(token),
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["upload_id"]

    await _settle_background_extraction(
        client,
        f"/v1/estimates/{upload_id}/status",
        auth_h(token),
        ("queued", "failed"),
    )

    from app.services.estimates import _extracted_key, _write_blob

    artifact = {"filename": "plan.pdf", "kind": "pdf", "summary": "s"}
    _write_blob(
        _extracted_key(upload_id, "plan.pdf.json"),
        json.dumps(artifact).encode("utf-8"),
    )

    # Agent-secret auth (the daemons' path).
    r = await client.get(
        f"/v1/estimates/{upload_id}/extracted/plan.pdf", headers=agent_h()
    )
    assert r.status_code == 200, r.text
    assert r.json() == artifact

    # Bearer-user auth also works.
    r = await client.get(
        f"/v1/estimates/{upload_id}/extracted/plan.pdf", headers=auth_h(token)
    )
    assert r.status_code == 200

    # Missing blob → 404 with detail.
    r = await client.get(
        f"/v1/estimates/{upload_id}/extracted/other.pdf", headers=agent_h()
    )
    assert r.status_code == 404

    # Unknown upload → 404.
    r = await client.get(
        "/v1/estimates/nope/extracted/plan.pdf", headers=agent_h()
    )
    assert r.status_code == 404

    # No auth → 401.
    r = await client.get(f"/v1/estimates/{upload_id}/extracted/plan.pdf")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Route-level: contracts
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_contracts_extracted_route(client, owner_token, tmp_path, monkeypatch):
    _, token = owner_token
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))

    resp = await client.post(
        "/v1/contracts/upload",
        files={"files": ("sub.pdf", _PDF, "application/pdf")},
        data={"project_label": "smoke", "contract_type": "subcontract"},
        headers=auth_h(token),
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["upload_id"]

    await _settle_background_extraction(
        client,
        f"/v1/contracts/{upload_id}/status",
        auth_h(token),
        ("extracted", "failed"),
    )

    from app.services.contracts import _extracted_key, _safe_name, _write_blob

    _write_blob(
        _extracted_key(upload_id, f"{_safe_name('sub.pdf')}.txt"),
        b"THE WHOLE SUBCONTRACT TEXT",
    )

    r = await client.get(
        f"/v1/contracts/{upload_id}/extracted/sub.pdf", headers=agent_h()
    )
    assert r.status_code == 200, r.text
    assert r.text == "THE WHOLE SUBCONTRACT TEXT"

    r = await client.get(
        f"/v1/contracts/{upload_id}/extracted/missing.pdf", headers=agent_h()
    )
    assert r.status_code == 404

    r = await client.get(
        "/v1/contracts/nope/extracted/sub.pdf", headers=agent_h()
    )
    assert r.status_code == 404

    r = await client.get(f"/v1/contracts/{upload_id}/extracted/sub.pdf")
    assert r.status_code == 401
