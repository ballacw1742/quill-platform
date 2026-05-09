"""Route tests for POST /v1/estimates/{upload_id}/dispatch_classification.

Covers:
- 200 (ok=true) when estimate exists and is in queued status.
- 404 when upload_id does not exist.
- 409 when estimate is already classified (classification_artifact_id set).
- 409 when estimate is not in queued status (e.g., extracting).
- Audit event is recorded on success.
"""

from __future__ import annotations

import io
import uuid

import pytest

from app.services.estimates import service as estimates_service
from tests.conftest import auth_h


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _tiny_pdf() -> bytes:
    """Minimal valid PDF for upload tests."""
    try:
        from reportlab.pdfgen import canvas  # type: ignore

        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        c.drawString(72, 720, "Dispatch classification test")
        c.showPage()
        c.save()
        return buf.getvalue()
    except ImportError:
        return (
            b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >> endobj\n"
            b"xref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000060 00000 n\n"
            b"0000000110 00000 n\n"
            b"trailer << /Size 4 /Root 1 0 R >>\nstartxref\n160\n%%EOF\n"
        )


async def _upload_and_get_id(client, token: str) -> str:
    """Upload a PDF and return the upload_id."""
    pdf = _tiny_pdf()
    resp = await client.post(
        "/v1/estimates/upload",
        files={"files": ("test.pdf", pdf, "application/pdf")},
        data={"project_label": "Dispatch Classification Test"},
        headers=auth_h(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["upload_id"]


# ---------------------------------------------------------------------------
# 200 — happy path
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_classification_ok(client, owner_token, session_maker):
    _, token = owner_token
    upload_id = await _upload_and_get_id(client, token)

    # Force status to queued (it may be extracting right after upload).
    async with session_maker() as s:
        await estimates_service.mark_status(
            s, upload_id, status="queued", actor="test"
        )

    resp = await client.post(
        f"/v1/estimates/{upload_id}/dispatch_classification",
        headers=auth_h(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["upload_id"] == upload_id
    assert "audit_hash" in data
    assert data["audit_hash"]  # non-empty


# ---------------------------------------------------------------------------
# 404 — upload does not exist
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_classification_404(client, owner_token):
    _, token = owner_token
    fake_id = str(uuid.uuid4())
    resp = await client.post(
        f"/v1/estimates/{fake_id}/dispatch_classification",
        headers=auth_h(token),
    )
    assert resp.status_code == 404
    assert "upload not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 409 — already classified
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_classification_409_already_classified(
    client, owner_token, session_maker
):
    _, token = owner_token
    upload_id = await _upload_and_get_id(client, token)

    # Stamp classification_artifact_id directly to simulate already-classified.
    from app.models import Estimate
    from sqlalchemy import select

    async with session_maker() as s:
        res = await s.execute(
            select(Estimate).where(Estimate.upload_id == upload_id)
        )
        est = res.scalar_one()
        est.classification_artifact_id = str(uuid.uuid4())
        est.status = "classifying"
        await s.commit()

    resp = await client.post(
        f"/v1/estimates/{upload_id}/dispatch_classification",
        headers=auth_h(token),
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "already" in detail.lower()


# ---------------------------------------------------------------------------
# 409 — not in queued status
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_classification_409_not_queued(
    client, owner_token, session_maker
):
    import asyncio

    _, token = owner_token
    upload_id = await _upload_and_get_id(client, token)

    # Let background extraction tasks complete so they don't overwrite our status.
    await asyncio.sleep(0.3)

    # Force to estimating status (extraction won't set this; it's post-classification).
    async with session_maker() as s:
        await estimates_service.mark_status(
            s, upload_id, status="estimating", actor="test"
        )

    resp = await client.post(
        f"/v1/estimates/{upload_id}/dispatch_classification",
        headers=auth_h(token),
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "queued" in detail.lower()


# ---------------------------------------------------------------------------
# 409 — failed status
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_classification_409_failed(
    client, owner_token, session_maker
):
    import asyncio

    _, token = owner_token
    upload_id = await _upload_and_get_id(client, token)

    # Let background extraction tasks complete first.
    await asyncio.sleep(0.3)

    async with session_maker() as s:
        await estimates_service.mark_status(
            s, upload_id, status="failed", actor="test"
        )

    resp = await client.post(
        f"/v1/estimates/{upload_id}/dispatch_classification",
        headers=auth_h(token),
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 401 — unauthenticated
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_classification_401(client, owner_token, session_maker):
    _, token = owner_token
    upload_id = await _upload_and_get_id(client, token)

    async with session_maker() as s:
        await estimates_service.mark_status(s, upload_id, status="queued", actor="test")

    resp = await client.post(
        f"/v1/estimates/{upload_id}/dispatch_classification"
        # No auth header
    )
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Audit event recorded
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_classification_records_audit_event(
    client, owner_token, session_maker
):
    _, token = owner_token
    upload_id = await _upload_and_get_id(client, token)

    async with session_maker() as s:
        await estimates_service.mark_status(s, upload_id, status="queued", actor="test")

    resp = await client.post(
        f"/v1/estimates/{upload_id}/dispatch_classification",
        headers=auth_h(token),
    )
    assert resp.status_code == 200

    # Verify audit entry exists in the DB.
    from app.models import AuditLogEntry
    from sqlalchemy import select

    async with session_maker() as s:
        res = await s.execute(
            select(AuditLogEntry).where(
                AuditLogEntry.event_type == "estimate.classification_dispatch_requested"
            )
        )
        entries = list(res.scalars().all())
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.payload["upload_id"] == upload_id
