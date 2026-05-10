"""Documents service HTTP surface \u2014 Phase D.1.

Endpoint contract per web/DOCUMENTS_SPEC.md \u00a7"API surface".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Document
from app.schemas import (
    DocumentDriveLinkOut,
    DocumentListPage,
    DocumentOut,
    DocumentReindexResult,
    DocumentSearchHit,
    DocumentSearchResult,
    DocumentSummary,
)
from app.security import get_current_user, require_admin_header
from app.services.documents import service as docs_service

router = APIRouter(prefix="/v1", tags=["documents"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _to_summary(d: Document) -> DocumentSummary:
    return DocumentSummary(
        id=d.id,
        artifact_id=d.artifact_id,
        artifact_type=d.artifact_type,
        title=d.title,
        summary=d.summary,
        agent_id=d.agent_id,
        agent_display_name=d.agent_display_name,
        created_at=d.created_at,
        approved_at=d.approved_at,
        tags=list(d.tags or []),
        drive_url=d.drive_url,
    )


def _to_full(d: Document) -> DocumentOut:
    return DocumentOut.model_validate(
        {
            "id": d.id,
            "artifact_id": d.artifact_id,
            "artifact_type": d.artifact_type,
            "title": d.title,
            "summary": d.summary,
            "body_markdown": d.body_markdown or "",
            "agent_id": d.agent_id,
            "agent_display_name": d.agent_display_name,
            "created_at": d.created_at,
            "approved_at": d.approved_at,
            "approved_by": d.approved_by,
            "approval_id": d.approval_id,
            "tags": list(d.tags or []),
            "drive_url": d.drive_url,
            "minio_path": d.minio_path,
            # Sprint G.7: surface the full artifact payload. Document.meta is
            # the Python attribute; DocumentOut.metadata is the schema field.
            "metadata": d.meta,
        }
    )


# ---------------------------------------------------------------------------
# List + get
# ---------------------------------------------------------------------------
@router.get(
    "/documents",
    response_model=DocumentListPage,
    summary="List documents",
)
async def list_documents(
    artifact_type: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    q: str | None = Query(default=None, min_length=1, max_length=256),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),  # noqa: ARG001
) -> DocumentListPage:
    docs, total = await docs_service.list(
        db,
        artifact_type=artifact_type,
        agent_id=agent_id,
        since=since,
        q=q,
        limit=limit,
        offset=offset,
    )
    return DocumentListPage(
        items=[_to_summary(d) for d in docs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/documents/search",
    response_model=DocumentSearchResult,
    summary="Full-text search",
)
async def search_documents(
    q: str = Query(..., min_length=1, max_length=256),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),  # noqa: ARG001
) -> DocumentSearchResult:
    hits, total = await docs_service.search(db, q, limit=limit)
    items = [
        DocumentSearchHit(
            id=d.id,
            artifact_id=d.artifact_id,
            artifact_type=d.artifact_type,
            title=d.title,
            summary=d.summary,
            agent_id=d.agent_id,
            agent_display_name=d.agent_display_name,
            created_at=d.created_at,
            snippet=snippet,
            score=score,
            tags=list(d.tags or []),
        )
        for (d, score, snippet) in hits
    ]
    return DocumentSearchResult(items=items, total=total, q=q)


@router.get(
    "/documents/{doc_id}",
    response_model=DocumentOut,
    summary="Get one document (full body)",
)
async def get_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),  # noqa: ARG001
) -> DocumentOut:
    doc = await docs_service.get(db, doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return _to_full(doc)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@router.get(
    "/documents/{doc_id}/export",
    summary="Export a document (md fully implemented; pdf/docx stubbed)",
)
async def export_document(
    doc_id: str,
    format: str = Query(default="md", pattern="^(md|pdf|docx)$"),
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),  # noqa: ARG001
) -> Response:
    try:
        body, content_type, filename = await docs_service.export(db, doc_id, fmt=format)
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return Response(
        content=body,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Drive link
# ---------------------------------------------------------------------------
@router.get(
    "/documents/{doc_id}/drive_link",
    response_model=DocumentDriveLinkOut,
    summary="Resolve the Google Drive copy URL (if any)",
)
async def get_drive_link(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),  # noqa: ARG001
) -> DocumentDriveLinkOut:
    try:
        info = await docs_service.drive_link(db, doc_id)
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    return DocumentDriveLinkOut(**info)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@router.post(
    "/admin/documents/reindex",
    response_model=DocumentReindexResult,
    summary="Rebuild the FTS index (admin)",
)
async def reindex_documents(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_header),
) -> DocumentReindexResult:
    res = await docs_service.reindex(db)
    return DocumentReindexResult(**res)
