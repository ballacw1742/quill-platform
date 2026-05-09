"""Estimates API tests \u2014 Phase G.1.

Covers the four endpoints from COST_SCHEDULE_SPEC \u00a7API:
- POST /v1/estimates/upload
- GET  /v1/estimates/{upload_id}/status
- POST /v1/estimates/{upload_id}/start_estimation
- GET  /v1/estimates/{upload_id}/export

Plus EstimatesService validation & lifecycle hook unit tests.
"""

from __future__ import annotations

import io
import os
import tempfile

import pytest

from app.services.estimates import (
    UploadValidationError,
    service as estimates_service,
)
from tests.conftest import auth_h


# ---------------------------------------------------------------------------
# Test PDF fixture (small valid PDF via reportlab when present)
# ---------------------------------------------------------------------------
def _tiny_pdf() -> bytes:
    try:
        from reportlab.pdfgen import canvas  # type: ignore

        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        c.drawString(72, 720, "Quill estimate test cover sheet")
        c.showPage()
        c.drawString(72, 720, "Site plan: cut/fill 145,000 CY")
        c.showPage()
        c.save()
        return buf.getvalue()
    except ImportError:
        return (
            b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >> endobj\n"
            b"xref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000060 00000 n\n0000000110 00000 n\n"
            b"trailer << /Size 4 /Root 1 0 R >>\nstartxref\n160\n%%EOF\n"
        )


# ---------------------------------------------------------------------------
# Service-level validation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_rejects_unsupported_kind(session_maker):
    async with session_maker() as s:
        with pytest.raises(UploadValidationError) as ei:
            await estimates_service.upload(
                s,
                files=[{"filename": "contract.docx", "size_bytes": 100,
                        "content": b"hello"}],
            )
        assert "unsupported" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_upload_rejects_too_many_files(session_maker):
    async with session_maker() as s:
        files = [
            {"filename": f"f{i}.pdf", "size_bytes": 10, "content": b"x"}
            for i in range(25)
        ]
        with pytest.raises(UploadValidationError):
            await estimates_service.upload(s, files=files)


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(session_maker):
    big = b"\x00" * 10
    async with session_maker() as s:
        with pytest.raises(UploadValidationError):
            await estimates_service.upload(
                s,
                files=[{
                    "filename": "huge.pdf",
                    "size_bytes": 250 * 1024 * 1024,  # 250 MB > cap
                    "content": big,
                }],
            )


# ---------------------------------------------------------------------------
# Upload + status
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_pdf_returns_upload_id(client, owner_token):
    user_id, token = owner_token
    pdf = _tiny_pdf()
    files = {
        "files": ("test.pdf", pdf, "application/pdf"),
    }
    data = {"project_label": "QPB1 — test", "notes": "smoke test"}
    r = await client.post(
        "/v1/estimates/upload",
        files=files,
        data=data,
        headers=auth_h(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["upload_id"]
    assert body["file_count"] == 1
    assert body["total_bytes"] == len(pdf)
    assert body["extraction_started"] is True


@pytest.mark.asyncio
async def test_upload_unsupported_format_returns_400(client, owner_token):
    user_id, token = owner_token
    files = {"files": ("contract.docx", b"hello world", "application/octet-stream")}
    r = await client.post(
        "/v1/estimates/upload",
        files=files,
        data={"project_label": "x"},
        headers=auth_h(token),
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_upload_no_files_returns_422(client, owner_token):
    user_id, token = owner_token
    # FastAPI validates absence of files at the multipart layer (422).
    r = await client.post(
        "/v1/estimates/upload",
        data={"project_label": "x"},
        headers=auth_h(token),
    )
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_status_returns_404_for_unknown_upload(client, owner_token):
    user_id, token = owner_token
    r = await client.get(
        "/v1/estimates/00000000-0000-0000-0000-000000000000/status",
        headers=auth_h(token),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_upload_then_get_status(client, owner_token):
    user_id, token = owner_token
    pdf = _tiny_pdf()
    r1 = await client.post(
        "/v1/estimates/upload",
        files={"files": ("plan.pdf", pdf, "application/pdf")},
        data={"project_label": "QPB1", "notes": "n"},
        headers=auth_h(token),
    )
    assert r1.status_code == 201
    upload_id = r1.json()["upload_id"]

    r2 = await client.get(
        f"/v1/estimates/{upload_id}/status",
        headers=auth_h(token),
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["upload_id"] == upload_id
    assert body["project_label"] == "QPB1"
    assert body["status"] in {"queued", "extracting", "failed"}
    assert isinstance(body["uploaded_files"], list)
    assert len(body["uploaded_files"]) == 1
    assert body["uploaded_files"][0]["filename"] == "plan.pdf"
    assert body["uploaded_files"][0]["kind"] == "pdf"


# ---------------------------------------------------------------------------
# start_estimation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_start_estimation_requires_classification(client, owner_token):
    user_id, token = owner_token
    pdf = _tiny_pdf()
    r1 = await client.post(
        "/v1/estimates/upload",
        files={"files": ("plan.pdf", pdf, "application/pdf")},
        data={"project_label": "x"},
        headers=auth_h(token),
    )
    upload_id = r1.json()["upload_id"]

    r = await client.post(
        f"/v1/estimates/{upload_id}/start_estimation",
        headers=auth_h(token),
    )
    assert r.status_code == 409, r.text  # classification not yet approved
    assert "classification" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_start_estimation_unknown_upload_returns_404(client, owner_token):
    user_id, token = owner_token
    r = await client.post(
        "/v1/estimates/nope/start_estimation",
        headers=auth_h(token),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_start_estimation_after_classification_dispatches(
    client, session_maker, owner_token
):
    user_id, token = owner_token
    pdf = _tiny_pdf()
    r1 = await client.post(
        "/v1/estimates/upload",
        files={"files": ("plan.pdf", pdf, "application/pdf")},
        data={"project_label": "x"},
        headers=auth_h(token),
    )
    upload_id = r1.json()["upload_id"]

    # Simulate the approval-execute hook firing for the classification.
    async with session_maker() as s:
        est = await estimates_service.on_classification_approved(
            s, upload_id=upload_id, artifact_id="aace-x"
        )
        assert est is not None
        assert est.classification_artifact_id == "aace-x"

    r = await client.post(
        f"/v1/estimates/{upload_id}/start_estimation",
        headers=auth_h(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["agent_id"] == "estimator-scheduler"
    assert body["audit_hash"]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_export_409_when_no_package(client, owner_token):
    user_id, token = owner_token
    pdf = _tiny_pdf()
    r1 = await client.post(
        "/v1/estimates/upload",
        files={"files": ("plan.pdf", pdf, "application/pdf")},
        data={"project_label": "x"},
        headers=auth_h(token),
    )
    upload_id = r1.json()["upload_id"]
    r = await client.get(
        f"/v1/estimates/{upload_id}/export?format=md",
        headers=auth_h(token),
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_export_unsupported_format(client, owner_token):
    user_id, token = owner_token
    r = await client.get(
        "/v1/estimates/whatever/export?format=docx",
        headers=auth_h(token),
    )
    # FastAPI Query pattern rejects with 422 before our handler runs.
    assert r.status_code in (422, 400)


@pytest.mark.asyncio
async def test_export_xer_returns_501(client, session_maker, owner_token):
    user_id, token = owner_token
    pdf = _tiny_pdf()
    r1 = await client.post(
        "/v1/estimates/upload",
        files={"files": ("plan.pdf", pdf, "application/pdf")},
        data={"project_label": "x"},
        headers=auth_h(token),
    )
    upload_id = r1.json()["upload_id"]

    # Simulate the package being approved with a published Document.
    from app.models import Document

    async with session_maker() as s:
        est = await estimates_service.on_package_approved(
            s, upload_id=upload_id, artifact_id="csp-x"
        )
        assert est is not None
        # Insert a Document row mapping to that artifact_id so export
        # can find it.
        from datetime import UTC, datetime

        s.add(
            Document(
                artifact_id="csp-x",
                artifact_type="cost_schedule_package",
                title="Test",
                summary="t",
                body_markdown="# Test",
                agent_id="estimator-scheduler",
                agent_display_name="Estimator-Scheduler",
                created_at=datetime.now(UTC),
            )
        )
        await s.commit()

    r = await client.get(
        f"/v1/estimates/{upload_id}/export?format=xer",
        headers=auth_h(token),
    )
    assert r.status_code == 501


@pytest.mark.asyncio
async def test_export_md_after_package_approved(
    client, session_maker, owner_token
):
    user_id, token = owner_token
    pdf = _tiny_pdf()
    r1 = await client.post(
        "/v1/estimates/upload",
        files={"files": ("plan.pdf", pdf, "application/pdf")},
        data={"project_label": "x"},
        headers=auth_h(token),
    )
    upload_id = r1.json()["upload_id"]

    from datetime import UTC, datetime

    from app.models import Document

    async with session_maker() as s:
        await estimates_service.on_package_approved(
            s, upload_id=upload_id, artifact_id="csp-final"
        )
        s.add(
            Document(
                artifact_id="csp-final",
                artifact_type="cost_schedule_package",
                title="QPB1 estimate",
                summary="Class 3 estimate",
                body_markdown=(
                    "# QPB1 estimate\n\nClass 3 control budget. Total $1.34B.\n"
                ),
                agent_id="estimator-scheduler",
                agent_display_name="Estimator-Scheduler",
                created_at=datetime.now(UTC),
            )
        )
        await s.commit()

    r = await client.get(
        f"/v1/estimates/{upload_id}/export?format=md",
        headers=auth_h(token),
    )
    assert r.status_code == 200, r.text
    assert b"QPB1 estimate" in r.content
    assert "text/markdown" in r.headers["content-type"]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_endpoints_require_auth(client):
    r = await client.get("/v1/estimates/x/status")
    assert r.status_code in (401, 403)
