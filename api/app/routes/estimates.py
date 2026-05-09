"""Estimates HTTP surface — Phase G.1.

Endpoint contract per COST_SCHEDULE_SPEC §API.

POST   /v1/estimates/upload                      multipart, returns upload_id
GET    /v1/estimates/{upload_id}/status          status + manifest
POST   /v1/estimates/{upload_id}/start_estimation dispatches estimator-scheduler
GET    /v1/estimates/{upload_id}/export?format=  md | csv | xer | pdf
"""

from __future__ import annotations

import io
import json
from datetime import datetime
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.security import get_current_user, get_current_user_or_agent
from app.services.estimates import (
    MAX_FILE_BYTES,
    MAX_FILE_COUNT,
    MAX_TOTAL_BYTES,
    UploadValidationError,
    service as estimates_service,
)

router = APIRouter(prefix="/v1/estimates", tags=["estimates"])


# ---------------------------------------------------------------------------
# Response shapes (inline; Phase G.2 will lift these into app/schemas.py
# alongside the rest of the public API surface).
# ---------------------------------------------------------------------------
class UploadFileEntry(BaseModel):
    filename: str
    kind: str
    size_bytes: int
    extraction_status: str
    extraction_summary: str = ""
    minio_key: str | None = None


class UploadOut(BaseModel):
    upload_id: str
    file_count: int
    total_bytes: int
    extraction_started: bool


class StatusOut(BaseModel):
    upload_id: str
    status: str
    project_label: str
    notes: str = ""
    uploaded_files: list[UploadFileEntry] = Field(default_factory=list)
    classification_artifact_id: str | None = None
    package_artifact_id: str | None = None
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None


class StartEstimationOut(BaseModel):
    ok: bool
    upload_id: str
    audit_hash: str
    agent_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _to_status(est: Any) -> StatusOut:
    return StatusOut(
        upload_id=est.upload_id,
        status=est.status,
        project_label=est.project_label or "",
        notes=est.notes or "",
        uploaded_files=[
            UploadFileEntry(**{
                "filename": f.get("filename", ""),
                "kind": f.get("kind", "other"),
                "size_bytes": int(f.get("size_bytes") or 0),
                "extraction_status": f.get("extraction_status") or "pending",
                "extraction_summary": f.get("extraction_summary") or "",
                "minio_key": f.get("minio_key"),
            })
            for f in (est.uploaded_files or [])
        ],
        classification_artifact_id=est.classification_artifact_id,
        package_artifact_id=est.package_artifact_id,
        created_at=est.created_at,
        updated_at=est.updated_at,
        error_message=est.error_message,
    )


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------
@router.post(
    "/upload",
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload design files for estimating",
)
async def upload_estimate(
    files: list[UploadFile] = File(...),
    project_label: str = Form(default=""),
    notes: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),  # noqa: ARG001
) -> UploadOut:
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no files")
    if len(files) > MAX_FILE_COUNT:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"too many files: {len(files)} > {MAX_FILE_COUNT}",
        )

    payloads: list[dict[str, Any]] = []
    total = 0
    for f in files:
        try:
            content = await f.read()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"failed to read {f.filename}: {exc}",
            ) from exc
        size = len(content)
        if size > MAX_FILE_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"{f.filename!r} exceeds per-file cap ({size} > {MAX_FILE_BYTES})",
            )
        total += size
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"upload exceeds total cap ({total} > {MAX_TOTAL_BYTES})",
            )
        payloads.append(
            {
                "filename": f.filename or "upload.bin",
                "size_bytes": size,
                "content": content,
            }
        )

    try:
        est = await estimates_service.upload(
            db,
            files=payloads,
            project_label=project_label,
            notes=notes,
        )
    except UploadValidationError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    return UploadOut(
        upload_id=est.upload_id,
        file_count=len(payloads),
        total_bytes=total,
        extraction_started=True,
    )


# ---------------------------------------------------------------------------
# GET /{upload_id}/status
# ---------------------------------------------------------------------------
@router.get(
    "/{upload_id}/status",
    response_model=StatusOut,
    summary="Get the status of an estimate run",
)
async def get_status_route(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user_or_agent),  # noqa: ARG001
) -> StatusOut:
    est = await estimates_service.get_status(db, upload_id)
    if est is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
    return _to_status(est)


# ---------------------------------------------------------------------------
# POST /{upload_id}/start_estimation
# ---------------------------------------------------------------------------
@router.post(
    "/{upload_id}/start_estimation",
    response_model=StartEstimationOut,
    summary="Dispatch the estimator-scheduler agent for an approved classification",
)
async def start_estimation_route(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),  # noqa: ARG001
) -> StartEstimationOut:
    try:
        info = await estimates_service.start_estimation(db, upload_id)
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except ValueError as e:
        # classification not yet approved → 409
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    return StartEstimationOut(**info)


# ---------------------------------------------------------------------------
# GET /{upload_id}/export
# ---------------------------------------------------------------------------
@router.get(
    "/{upload_id}/export",
    summary="Export an estimate package (md | csv | xer | pdf)",
)
async def export_estimate(
    upload_id: str,
    format: str = Query(default="md", pattern="^(md|csv|xer|pdf)$"),
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user_or_agent),  # noqa: ARG001
) -> Response:
    est = await estimates_service.get_status(db, upload_id)
    if est is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
    if est.package_artifact_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "cost_schedule_package not yet approved; nothing to export",
        )

    # v0.1: load the published Document for the package and render a
    # format-appropriate export. Real CSV / XER / PDF exporters land in
    # G.2 (CSV) and G.4 (XER, PDF). md path is fully implemented today.
    from app.models import Document
    from sqlalchemy import select

    res = await db.execute(
        select(Document).where(Document.artifact_id == est.package_artifact_id)
    )
    doc = res.scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "package document not found (artifact_id={})".format(
                est.package_artifact_id
            ),
        )

    if format == "md":
        body = (doc.body_markdown or "").encode("utf-8")
        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="estimate-{upload_id}.md"'
                )
            },
        )

    if format == "csv":
        # Pull the cost rows out of the published artifact's metadata if
        # present; fall back to a stub.
        rows = []
        try:
            # Documents store body_markdown only. The structured estimate
            # rows live in the original ApprovalItem.payload.artifact.metadata
            # — for v0.1 we render a header-only CSV so the UI wires up.
            pass
        except Exception:  # noqa: BLE001
            rows = []
        out = io.StringIO()
        out.write(
            "csi_section,description,quantity,unit,unit_rate_usd,extended_usd,"
            "rate_source,confidence,notes\n"
        )
        # Actual row rendering ships in G.2 once Documents stores the
        # full artifact JSON next to body_markdown. For now this is a
        # well-formed CSV scaffold so the export pipeline is exercisable.
        return Response(
            content=out.getvalue().encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="estimate-{upload_id}.csv"'
                )
            },
        )

    if format == "xer":
        # Primavera P6 XER export — Phase G.4.
        # Pull the full artifact (with schedule.activities + relationships)
        # from the ApprovalItem.payload that produced this Document.
        from app.models import ApprovalItem
        from app.services.xer import ScheduleToXer

        package_artifact: dict[str, Any] | None = None
        if doc.approval_id:
            ar = await db.execute(
                select(ApprovalItem).where(ApprovalItem.id == doc.approval_id)
            )
            appr = ar.scalar_one_or_none()
            if appr is not None:
                payload = appr.payload or {}
                package_artifact = (
                    payload.get("artifact")
                    or payload.get("proposed_action", {}).get("artifact")
                    or payload
                )
        if not package_artifact:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "package artifact not available for XER export (approval item missing payload.artifact)",
            )
        try:
            xer_text = ScheduleToXer(
                project_id=(est.project_label or "QPB1")[:20] or "QPB1",
                project_name=est.project_label or "Quill Estimate",
            ).generate_xer(package_artifact)
        except ValueError as e:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"XER export failed: {e}",
            ) from e
        return Response(
            content=xer_text.encode("utf-8"),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="estimate-{upload_id}.xer"'
                )
            },
        )

    if format == "pdf":
        # PDF export ships with the Documents pipeline in G.4. For now
        # return a stub that says so, with the markdown body inline.
        stub = (
            f"# {doc.title}\n\n"
            f"_PDF export is stubbed in v0.1. The Markdown body follows:_\n\n"
            f"{doc.body_markdown or ''}"
        ).encode("utf-8")
        return Response(
            content=stub,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="estimate-{upload_id}.pdf.md"'
                )
            },
        )

    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unsupported format: {format}")
