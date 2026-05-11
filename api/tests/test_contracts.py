"""Contracts API tests — Sprint Contracts.1.

Covers:
- POST /v1/contracts/upload (happy path + size cap)
- GET  /v1/contracts (list with filters)
- GET  /v1/contracts/{upload_id} (200 / 404)
- GET  /v1/contracts/{upload_id}/status
- POST /v1/contracts/{upload_id}/dispatch_extraction (200 / 404 / 409)
- POST /v1/contracts/{upload_id}/cancel
"""

from __future__ import annotations

import io
from typing import Any

import pytest

from app.services.contracts import (
    ContractUploadValidationError,
    service as contracts_service,
)
from tests.conftest import auth_h

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _tiny_pdf() -> bytes:
    """Return a minimal valid PDF for testing."""
    return (
        b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >> endobj\n"
        b"xref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000060 00000 n\n"
        b"0000000110 00000 n\n"
        b"trailer << /Size 4 /Root 1 0 R >>\nstartxref\n160\n%%EOF\n"
    )


def _tiny_txt() -> bytes:
    return b"This is a subcontract between Acme Construction and Beta Subs LLC."


# ---------------------------------------------------------------------------
# Service-level validation tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_rejects_no_files(session_maker):
    async with session_maker() as s:
        with pytest.raises(ContractUploadValidationError, match="no files"):
            await contracts_service.upload(s, files=[])


@pytest.mark.asyncio
async def test_upload_rejects_too_many_files(session_maker):
    async with session_maker() as s:
        files = [
            {"filename": f"f{i}.pdf", "size_bytes": 10, "content": b"x"}
            for i in range(15)
        ]
        with pytest.raises(ContractUploadValidationError, match="too many"):
            await contracts_service.upload(s, files=files)


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(session_maker):
    from app.services.contracts import MAX_FILE_BYTES

    async with session_maker() as s:
        with pytest.raises(ContractUploadValidationError, match="per-file cap"):
            await contracts_service.upload(
                s,
                files=[
                    {
                        "filename": "big.pdf",
                        "size_bytes": MAX_FILE_BYTES + 1,
                        "content": b"x" * 100,  # fake small content, size_bytes is the check
                    }
                ],
            )


@pytest.mark.asyncio
async def test_upload_rejects_invalid_contract_type(session_maker):
    async with session_maker() as s:
        with pytest.raises(ContractUploadValidationError, match="unknown contract_type"):
            await contracts_service.upload(
                s,
                files=[{"filename": "c.pdf", "size_bytes": 10, "content": b"x"}],
                contract_type="bogus_type",
            )


@pytest.mark.asyncio
async def test_upload_happy_path(session_maker, tmp_path, monkeypatch):
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))

    async with session_maker() as s:
        contract = await contracts_service.upload(
            s,
            files=[
                {"filename": "subcontract.pdf", "size_bytes": len(_tiny_pdf()), "content": _tiny_pdf()}
            ],
            project_label="Test Project",
            contract_type="subcontract",
            notes="Test notes",
        )

    assert contract.upload_id is not None
    assert contract.status == "uploaded"
    assert contract.project_label == "Test Project"
    assert contract.contract_type == "subcontract"
    assert len(contract.uploaded_files) == 1
    assert contract.uploaded_files[0]["filename"] == "subcontract.pdf"


@pytest.mark.asyncio
async def test_list_contracts(session_maker, tmp_path, monkeypatch):
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))

    async with session_maker() as s:
        await contracts_service.upload(
            s,
            files=[{"filename": "c1.txt", "size_bytes": 10, "content": _tiny_txt()}],
            project_label="Project A",
        )
        await contracts_service.upload(
            s,
            files=[{"filename": "c2.txt", "size_bytes": 10, "content": _tiny_txt()}],
            project_label="Project B",
            contract_type="change_order",
        )

    async with session_maker() as s:
        items, total = await contracts_service.list_contracts(s)
        assert total == 2
        assert len(items) == 2

    async with session_maker() as s:
        items, total = await contracts_service.list_contracts(s, contract_type="change_order")
        assert total == 1
        assert items[0].contract_type == "change_order"


@pytest.mark.asyncio
async def test_mark_status(session_maker, tmp_path, monkeypatch):
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))

    async with session_maker() as s:
        contract = await contracts_service.upload(
            s,
            files=[{"filename": "c.txt", "size_bytes": 10, "content": b"test"}],
        )
        upload_id = contract.upload_id

    async with session_maker() as s:
        updated = await contracts_service.mark_status(
            s, upload_id, status="extracting"
        )
        assert updated.status == "extracting"

    async with session_maker() as s:
        updated = await contracts_service.mark_status(
            s, upload_id, status="failed", error_message="test failure"
        )
        assert updated.status == "failed"
        assert "test failure" in updated.error_message


@pytest.mark.asyncio
async def test_mark_status_invalid(session_maker, tmp_path, monkeypatch):
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))

    async with session_maker() as s:
        contract = await contracts_service.upload(
            s,
            files=[{"filename": "c.txt", "size_bytes": 5, "content": b"hello"}],
        )
        upload_id = contract.upload_id

    async with session_maker() as s:
        with pytest.raises(ValueError, match="invalid status"):
            await contracts_service.mark_status(s, upload_id, status="bogus_state")


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_route_happy(client, owner_token, tmp_path, monkeypatch):
    _, token = owner_token
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))
    resp = await client.post(
        "/v1/contracts/upload",
        files={"files": ("contract.pdf", _tiny_pdf(), "application/pdf")},
        data={"project_label": "My Project", "contract_type": "owner_gc"},
        headers=auth_h(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "upload_id" in body
    assert body["file_count"] == 1
    assert body["extraction_started"] is True


@pytest.mark.asyncio
async def test_upload_route_no_files(client, owner_token):
    _, token = owner_token
    resp = await client.post(
        "/v1/contracts/upload",
        headers=auth_h(token),
    )
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_upload_route_size_cap(client, owner_token, tmp_path, monkeypatch):
    _, token = owner_token
    from app.services.contracts import MAX_FILE_BYTES

    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))
    big_content = b"x" * (MAX_FILE_BYTES + 1)
    resp = await client.post(
        "/v1/contracts/upload",
        files={"files": ("big.pdf", big_content, "application/pdf")},
        headers=auth_h(token),
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_list_route(client, owner_token, tmp_path, monkeypatch):
    _, token = owner_token
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))
    for i in range(2):
        r = await client.post(
            "/v1/contracts/upload",
            files={"files": (f"c{i}.txt", _tiny_txt(), "text/plain")},
            headers=auth_h(token),
        )
        assert r.status_code == 201

    resp = await client.get(
        "/v1/contracts",
        headers=auth_h(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert body["total"] >= 2


@pytest.mark.asyncio
async def test_list_route_status_filter(client, owner_token, tmp_path, monkeypatch):
    _, token = owner_token
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))
    resp = await client.get(
        "/v1/contracts?status=uploaded",
        headers=auth_h(token),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_route_invalid_filter(client, owner_token):
    _, token = owner_token
    resp = await client.get(
        "/v1/contracts?status=not_a_real_status",
        headers=auth_h(token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_route_200(client, owner_token, tmp_path, monkeypatch):
    _, token = owner_token
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))
    up = await client.post(
        "/v1/contracts/upload",
        files={"files": ("c.txt", _tiny_txt(), "text/plain")},
        headers=auth_h(token),
    )
    upload_id = up.json()["upload_id"]

    resp = await client.get(
        f"/v1/contracts/{upload_id}",
        headers=auth_h(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["upload_id"] == upload_id
    assert "disclaimer" in body
    assert "legal advice" in body["disclaimer"].lower()


@pytest.mark.asyncio
async def test_get_route_404(client, owner_token):
    _, token = owner_token
    resp = await client.get(
        "/v1/contracts/nonexistent-upload-id",
        headers=auth_h(token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_status_route_200(client, owner_token, tmp_path, monkeypatch):
    _, token = owner_token
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))
    up = await client.post(
        "/v1/contracts/upload",
        files={"files": ("c.txt", _tiny_txt(), "text/plain")},
        headers=auth_h(token),
    )
    upload_id = up.json()["upload_id"]

    resp = await client.get(
        f"/v1/contracts/{upload_id}/status",
        headers=auth_h(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["upload_id"] == upload_id
    assert "status" in body


@pytest.mark.asyncio
async def test_dispatch_extraction_200(client, owner_token, tmp_path, monkeypatch):
    """dispatch_extraction returns 200 for a contract in uploaded/extracted/failed status.

    We suppress the background text-extraction task so the contract stays in
    'uploaded' state when we hit dispatch_extraction.
    """
    _, token = owner_token
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))
    # Suppress background extraction to keep status='uploaded'
    import app.services.contracts as _csvc
    monkeypatch.setattr(_csvc.service, "_run_extraction_async", lambda uid: _noop_coro())

    up = await client.post(
        "/v1/contracts/upload",
        files={"files": ("c.txt", _tiny_txt(), "text/plain")},
        headers=auth_h(token),
    )
    assert up.status_code == 201, up.text
    upload_id = up.json()["upload_id"]

    resp = await client.post(
        f"/v1/contracts/{upload_id}/dispatch_extraction",
        headers=auth_h(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["upload_id"] == upload_id
    assert "audit_hash" in body


@pytest.mark.asyncio
async def test_dispatch_extraction_404(client, owner_token):
    _, token = owner_token
    resp = await client.post(
        "/v1/contracts/nonexistent-id/dispatch_extraction",
        headers=auth_h(token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dispatch_extraction_409_already_extracted(client, owner_token, tmp_path, monkeypatch, session_maker):
    """409 if extracted_fields already populated."""
    _, token = owner_token
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))
    up = await client.post(
        "/v1/contracts/upload",
        files={"files": ("c.txt", _tiny_txt(), "text/plain")},
        headers=auth_h(token),
    )
    upload_id = up.json()["upload_id"]

    from app.models import Contract
    from sqlalchemy import select

    async with session_maker() as s:
        res = await s.execute(select(Contract).where(Contract.upload_id == upload_id))
        c = res.scalar_one()
        c.extracted_fields = {"artifact_type": "contract_extraction", "contract_type": "subcontract"}
        await s.commit()

    resp = await client.post(
        f"/v1/contracts/{upload_id}/dispatch_extraction",
        headers=auth_h(token),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_dispatch_extraction_409_wrong_status(client, owner_token, tmp_path, monkeypatch, session_maker):
    """409 if status is not uploaded/extracted/failed.

    The background _run_extraction_async task races with us: by the time
    we manually set status=reviewing and commit, that task has already
    finished its own run and overwritten status back to extracted. Stub
    it out for this test so the manual status set is the source of truth.
    """
    _, token = owner_token
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))

    from app.services.contracts import service as contracts_service

    async def _noop_extraction(_upload_id: str) -> None:
        return None

    monkeypatch.setattr(
        contracts_service, "_run_extraction_async", _noop_extraction
    )

    up = await client.post(
        "/v1/contracts/upload",
        files={"files": ("c.txt", _tiny_txt(), "text/plain")},
        headers=auth_h(token),
    )
    upload_id = up.json()["upload_id"]

    from app.models import Contract
    from sqlalchemy import select

    async with session_maker() as s:
        res = await s.execute(select(Contract).where(Contract.upload_id == upload_id))
        c = res.scalar_one()
        c.status = "reviewing"  # not in dispatchable set
        await s.commit()

    resp = await client.post(
        f"/v1/contracts/{upload_id}/dispatch_extraction",
        headers=auth_h(token),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cancel_route(client, owner_token, tmp_path, monkeypatch):
    _, token = owner_token
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))
    up = await client.post(
        "/v1/contracts/upload",
        files={"files": ("c.txt", _tiny_txt(), "text/plain")},
        headers=auth_h(token),
    )
    upload_id = up.json()["upload_id"]

    resp = await client.post(
        f"/v1/contracts/{upload_id}/cancel",
        data={"reason": "testing cancel"},
        headers=auth_h(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True


@pytest.mark.asyncio
async def test_cancel_idempotent(client, owner_token, tmp_path, monkeypatch):
    """Cancelling an already-failed contract returns 200 (idempotent)."""
    _, token = owner_token
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))
    up = await client.post(
        "/v1/contracts/upload",
        files={"files": ("c.txt", _tiny_txt(), "text/plain")},
        headers=auth_h(token),
    )
    upload_id = up.json()["upload_id"]

    r1 = await client.post(
        f"/v1/contracts/{upload_id}/cancel",
        headers=auth_h(token),
    )
    assert r1.status_code == 200

    r2 = await client.post(
        f"/v1/contracts/{upload_id}/cancel",
        headers=auth_h(token),
    )
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_disclaimer_always_present(client, owner_token, tmp_path, monkeypatch):
    """ContractOut always includes a disclaimer regardless of extraction state."""
    _, token = owner_token
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))
    up = await client.post(
        "/v1/contracts/upload",
        files={"files": ("c.txt", _tiny_txt(), "text/plain")},
        headers=auth_h(token),
    )
    upload_id = up.json()["upload_id"]

    resp = await client.get(
        f"/v1/contracts/{upload_id}",
        headers=auth_h(token),
    )
    body = resp.json()
    assert body["disclaimer"] == (
        "AI-generated analysis. This is not legal advice. "
        "Review with qualified counsel before relying on it for any binding decision."
    )
