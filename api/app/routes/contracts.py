"""Contracts HTTP surface — Sprint Contracts.1 + Contracts.2.

POST   /v1/contracts/upload                         multipart, returns upload_id
GET    /v1/contracts                                list with optional filters
GET    /v1/contracts/{upload_id}                    full record
GET    /v1/contracts/{upload_id}/status             lightweight status
POST   /v1/contracts/{upload_id}/dispatch_extraction schedule agent extraction
POST   /v1/contracts/{upload_id}/cancel             idempotent cancel

# Contracts.2 additions:
POST   /v1/contracts/{upload_id}/dispatch_review    schedule contract-reviewer agent
POST   /v1/contracts/{upload_id}/interpret          sync Q&A about a contract clause
GET    /v1/contracts/{upload_id}/reviews            list past reviews
GET    /v1/contracts/{upload_id}/interpretations    Q&A history
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status as http_status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas import (
    ContractListPage,
    ContractListItem,
    ContractOut,
    ContractStatusOut,
    ContractUploadOut,
    ContractInterpretationOut,
    ContractReviewListPage,
    ContractReviewListItem,
    ContractReviewSeverityCounts,
    ContractInterpretationListPage,
    _DispatchReviewOut,
    _InterpretRequest,
    _CONTRACT_DISCLAIMER,
    # Contracts.3
    ContractTemplateOut,
    ContractTemplateListResponse,
    ContractDraftRequest,
    RedraftRequest,
)
from app.security import get_current_user, get_current_user_or_agent
from app.services import audit as audit_svc
from app.services.contracts import (
    MAX_FILE_BYTES,
    MAX_FILE_COUNT,
    MAX_TOTAL_BYTES,
    ContractUploadValidationError,
    service as contracts_service,
)

router = APIRouter(prefix="/v1/contracts", tags=["contracts"])

_DISPATCH_STATUSES = {"uploaded", "extracted", "failed"}
_REVIEW_DISPATCH_STATUSES = {"extracted", "reviewed", "failed"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _to_out(c: Any) -> ContractOut:
    return ContractOut(
        upload_id=c.upload_id,
        project_label=c.project_label or "",
        contract_type=c.contract_type,
        status=c.status,
        source=c.source or "upload",
        uploaded_files=list(c.uploaded_files or []),
        extracted_fields=c.extracted_fields,
        parties=list(c.parties or []),
        effective_date=c.effective_date,
        expiration_date=c.expiration_date,
        total_value_usd=float(c.total_value_usd) if c.total_value_usd is not None else None,
        notes=c.notes or "",
        error_message=c.error_message,
        classification_artifact_id=c.classification_artifact_id,
        review_artifact_id=c.review_artifact_id,
        # Contracts.3 fields
        draft_request=c.draft_request,
        draft_artifact_id=c.draft_artifact_id,
        mode=c.mode,
        created_at=c.created_at,
        updated_at=c.updated_at,
        disclaimer=_CONTRACT_DISCLAIMER,
    )


def _to_list_item(c: Any) -> ContractListItem:
    return ContractListItem(
        upload_id=c.upload_id,
        project_label=c.project_label or "",
        contract_type=c.contract_type,
        status=c.status,
        source=c.source or "upload",
        effective_date=c.effective_date,
        expiration_date=c.expiration_date,
        total_value_usd=float(c.total_value_usd) if c.total_value_usd is not None else None,
        created_at=c.created_at,
        updated_at=c.updated_at,
        error_message=c.error_message,
    )


def _to_status(c: Any) -> ContractStatusOut:
    return ContractStatusOut(
        upload_id=c.upload_id,
        status=c.status,
        contract_type=c.contract_type,
        effective_date=c.effective_date,
        expiration_date=c.expiration_date,
        error_message=c.error_message,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------
@router.post(
    "/upload",
    response_model=ContractUploadOut,
    status_code=http_status.HTTP_201_CREATED,
    summary="Upload contract files for extraction",
)
async def upload_contract(
    files: list[UploadFile] = File(...),
    project_label: str = Form(default=""),
    contract_type: str | None = Form(default=None),
    notes: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),  # noqa: ARG001
) -> ContractUploadOut:
    if not files:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, "no files provided")
    if len(files) > MAX_FILE_COUNT:
        raise HTTPException(
            http_status.HTTP_400_BAD_REQUEST,
            f"too many files: {len(files)} > {MAX_FILE_COUNT}",
        )

    payloads: list[dict[str, Any]] = []
    total = 0
    for f in files:
        try:
            content = await f.read()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                http_status.HTTP_400_BAD_REQUEST,
                f"failed to read {f.filename}: {exc}",
            ) from exc
        size = len(content)
        if size > MAX_FILE_BYTES:
            raise HTTPException(
                http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"{f.filename!r} exceeds per-file cap ({size} > {MAX_FILE_BYTES})",
            )
        total += size
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(
                http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
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
        contract = await contracts_service.upload(
            db,
            files=payloads,
            project_label=project_label,
            contract_type=contract_type or None,
            notes=notes,
            actor=getattr(user, "id", "system"),
        )
    except ContractUploadValidationError as e:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, str(e)) from e

    return ContractUploadOut(
        upload_id=contract.upload_id,
        file_count=len(payloads),
        total_bytes=total,
        extraction_started=True,
    )


# ---------------------------------------------------------------------------
# GET / (list)
# ---------------------------------------------------------------------------
@router.get(
    "",
    response_model=ContractListPage,
    summary="List contracts (most recent first)",
)
async def list_contracts_route(
    status_filter: str | None = Query(
        default=None, alias="status", description="Optional status filter"
    ),
    contract_type: str | None = Query(
        default=None, description="Optional contract_type filter"
    ),
    source: str | None = Query(
        default=None, description="Optional source filter (upload | drafted)"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user_or_agent),  # noqa: ARG001
) -> ContractListPage:
    try:
        items, total = await contracts_service.list_contracts(
            db,
            status=status_filter,
            contract_type=contract_type,
            source=source,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, str(e)) from e

    return ContractListPage(
        items=[_to_list_item(c) for c in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Contracts.3 — GET /templates  (declared BEFORE /{upload_id} so FastAPI's
# greedy path matcher doesn't route 'templates' as an upload_id)
# ---------------------------------------------------------------------------
@router.get(
    "/templates",
    response_model=ContractTemplateListResponse,
    summary="List available contract templates",
)
async def list_templates_route(
    user: Any = Depends(get_current_user),  # noqa: ARG001
) -> ContractTemplateListResponse:
    """Return metadata for all available contract templates."""
    from app.services.contract_templates import list_templates

    items_raw = list_templates()
    items = [ContractTemplateOut(**t) for t in items_raw]
    return ContractTemplateListResponse(items=items, total=len(items))


# ---------------------------------------------------------------------------
# Contracts.3 — GET /templates/{template_id}
# ---------------------------------------------------------------------------
@router.get(
    "/templates/{template_id}",
    response_model=ContractTemplateOut,
    summary="Get a single contract template",
)
async def get_template_route(
    template_id: str,
    user: Any = Depends(get_current_user),  # noqa: ARG001
) -> ContractTemplateOut:
    """Return frontmatter + body for a single template."""
    from app.services.contract_templates import get_template

    tmpl = get_template(template_id)
    if tmpl is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, f"template {template_id!r} not found")
    return ContractTemplateOut(**tmpl)


# ---------------------------------------------------------------------------
# GET /{upload_id}
# ---------------------------------------------------------------------------
@router.get(
    "/{upload_id}",
    response_model=ContractOut,
    summary="Get full contract record",
)
async def get_contract_route(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user_or_agent),  # noqa: ARG001
) -> ContractOut:
    contract = await contracts_service.get_status(db, upload_id)
    if contract is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "contract not found")
    return _to_out(contract)


# ---------------------------------------------------------------------------
# GET /{upload_id}/status
# ---------------------------------------------------------------------------
@router.get(
    "/{upload_id}/status",
    response_model=ContractStatusOut,
    summary="Lightweight status check",
)
async def get_contract_status_route(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user_or_agent),  # noqa: ARG001
) -> ContractStatusOut:
    contract = await contracts_service.get_status(db, upload_id)
    if contract is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "contract not found")
    return _to_status(contract)


# ---------------------------------------------------------------------------
# GET /{upload_id}/extracted/{filename} — Sprint 4 (remote daemons)
# ---------------------------------------------------------------------------
@router.get(
    "/{upload_id}/extracted/{filename}",
    summary="Fetch the full extracted text for one uploaded file (daemon/agent use)",
)
async def get_extracted_text_route(
    upload_id: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user_or_agent),  # noqa: ARG001
):
    """Serve the extracted plain text written during background extraction.

    Sprint 4: the contract dispatcher daemons can run on a different host
    than the API; the manifest's ``extraction_summary`` caps at 4000 chars,
    so full-fidelity extraction needs this HTTP path. Auth: any authenticated
    user or the agent service account (X-Agent-Secret).
    """
    from fastapi.responses import PlainTextResponse

    contract = await contracts_service.get_status(db, upload_id)
    if contract is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "contract not found")
    text = contracts_service.read_extracted_text(upload_id, filename)
    if text is None:
        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            f"extracted text not found for {filename!r}",
        )
    return PlainTextResponse(text)


# ---------------------------------------------------------------------------
# POST /{upload_id}/dispatch_extraction
# ---------------------------------------------------------------------------
class DispatchExtractionOut:
    """Return shape for dispatch_extraction."""

    ok: bool
    upload_id: str
    audit_hash: str


from pydantic import BaseModel


class _DispatchExtractionOut(BaseModel):
    ok: bool
    upload_id: str
    audit_hash: str


@router.post(
    "/{upload_id}/dispatch_extraction",
    response_model=_DispatchExtractionOut,
    summary="Request contract-extractor agent dispatch",
)
async def dispatch_extraction_route(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> _DispatchExtractionOut:
    """Signal that the contract-extractor daemon should pick up this contract.

    - 404 if not found.
    - 409 if ``extracted_fields`` is already populated, or status not in
      (``uploaded``, ``extracted``, ``failed``).
    - Writes a priority marker for the contract-extractor daemon.
    - Records an audit event.
    """
    contract = await contracts_service.get_status(db, upload_id)
    if contract is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "contract not found")

    if contract.extracted_fields is not None:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "extracted_fields already populated for this contract",
        )
    if contract.status not in _DISPATCH_STATUSES:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            f"contract is not in a dispatchable status (current: {contract.status}); "
            f"must be one of {sorted(_DISPATCH_STATUSES)}",
        )

    # Write a priority marker for the daemon.
    try:
        repo_root = Path(__file__).resolve().parents[3]
        marker_dir = repo_root / "_state" / "contract_dispatch_requests"
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker = marker_dir / f"{upload_id}.json"
        marker.write_text(
            json.dumps(
                {
                    "upload_id": upload_id,
                    "requested_at": datetime.now(UTC).isoformat(),
                    "requested_by": getattr(user, "id", str(user)),
                }
            ),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger("quill.contracts").warning(
            "dispatch_extraction.marker_write_failed upload_id=%s err=%s",
            upload_id, exc,
        )
        # Non-fatal — the daemon polls all extracted contracts anyway.

    entry = await audit_svc.record_event(
        db,
        event_type="contract.extraction_dispatch_requested",
        actor=getattr(user, "id", "system"),
        approval_item_id=None,
        payload={
            "upload_id": upload_id,
            "contract_id": contract.id,
            "project_label": contract.project_label,
        },
    )
    await db.commit()

    return _DispatchExtractionOut(
        ok=True,
        upload_id=upload_id,
        audit_hash=entry.hash,
    )


# ---------------------------------------------------------------------------
# POST /{upload_id}/cancel
# ---------------------------------------------------------------------------
class _CancelOut(BaseModel):
    ok: bool
    upload_id: str


@router.post(
    "/{upload_id}/cancel",
    response_model=_CancelOut,
    summary="Cancel (fail) a contract upload",
)
async def cancel_contract_route(
    upload_id: str,
    reason: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> _CancelOut:
    """Idempotent cancel — sets status to ``failed``.

    If already ``failed`` this is a no-op (still returns 200).
    """
    contract = await contracts_service.get_status(db, upload_id)
    if contract is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "contract not found")

    if contract.status == "failed":
        return _CancelOut(ok=True, upload_id=upload_id)

    await contracts_service.mark_status(
        db,
        upload_id,
        status="failed",
        error_message=reason or "cancelled by user",
        actor=getattr(user, "id", "system"),
    )
    return _CancelOut(ok=True, upload_id=upload_id)


# ---------------------------------------------------------------------------
# Contracts.2 — POST /{upload_id}/dispatch_review
# ---------------------------------------------------------------------------
@router.post(
    "/{upload_id}/dispatch_review",
    response_model=_DispatchReviewOut,
    summary="Request contract-reviewer agent dispatch",
)
async def dispatch_review_route(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> _DispatchReviewOut:
    """Signal that the contract-reviewer daemon should pick up this contract.

    - 404 if not found.
    - 409 if extracted_fields is NULL (must run extraction first) or status
      not in (extracted, reviewed, failed).
    - Writes a priority marker for the contract-review-dispatcher daemon.
    - Records an audit event.
    """
    contract = await contracts_service.get_status(db, upload_id)
    if contract is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "contract not found")

    if contract.extracted_fields is None:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "extraction not yet complete; run dispatch_extraction first",
        )
    if contract.status not in _REVIEW_DISPATCH_STATUSES:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            f"contract is not in a reviewable status (current: {contract.status}); "
            f"must be one of {sorted(_REVIEW_DISPATCH_STATUSES)}",
        )

    # Write a priority marker for the review daemon.
    try:
        repo_root = Path(__file__).resolve().parents[3]
        marker_dir = repo_root / "_state" / "contract_review_requests"
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker = marker_dir / f"{upload_id}.json"
        marker.write_text(
            json.dumps(
                {
                    "upload_id": upload_id,
                    "requested_at": datetime.now(UTC).isoformat(),
                    "requested_by": getattr(user, "id", str(user)),
                }
            ),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        import logging as _logging
        _logging.getLogger("quill.contracts").warning(
            "dispatch_review.marker_write_failed upload_id=%s err=%s",
            upload_id, exc,
        )
        # Non-fatal — the daemon polls all extracted contracts anyway.

    entry = await audit_svc.record_event(
        db,
        event_type="contract.review_dispatch_requested",
        actor=getattr(user, "id", "system"),
        approval_item_id=None,
        payload={
            "upload_id": upload_id,
            "contract_id": contract.id,
            "project_label": contract.project_label,
        },
    )
    await db.commit()

    return _DispatchReviewOut(
        ok=True,
        upload_id=upload_id,
        audit_hash=entry.hash,
    )


# ---------------------------------------------------------------------------
# Contracts.2 — POST /{upload_id}/interpret
# ---------------------------------------------------------------------------
@router.post(
    "/{upload_id}/interpret",
    response_model=ContractInterpretationOut,
    summary="Ask a plain-English question about a contract clause (synchronous)",
)
async def interpret_contract_route(
    upload_id: str,
    body: _InterpretRequest,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> ContractInterpretationOut:
    """Synchronous plain-English Q&A about a contract clause.

    - 404 if contract not found.
    - 409 if extraction not yet complete (extracted_fields is NULL).
    - 400 if question is empty or > 500 chars.
    - Invokes contract-interpreter agent in-process, persists Q&A row.
    """
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, "question is required")
    if len(question) > 500:
        raise HTTPException(
            http_status.HTTP_400_BAD_REQUEST,
            f"question too long: {len(question)} chars > 500",
        )

    contract = await contracts_service.get_status(db, upload_id)
    if contract is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "contract not found")
    if contract.extracted_fields is None:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "extraction not yet complete for this contract; run dispatch_extraction first",
        )

    try:
        result = await contracts_service.interpret_clause(
            db,
            upload_id=upload_id,
            question=question,
            user=user,
        )
    except LookupError as e:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, str(e)) from e
    except ValueError as e:
        raise HTTPException(http_status.HTTP_409_CONFLICT, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(http_status.HTTP_502_BAD_GATEWAY, f"agent error: {e}") from e

    return ContractInterpretationOut(
        contract_upload_id=upload_id,
        question=result.get("question", question),
        answer=result.get("answer", ""),
        supporting_clauses=result.get("supporting_clauses", []),
        confidence=result.get("confidence", 0.0),
        caveats=result.get("caveats", []),
        disclaimer=result.get("disclaimer", _CONTRACT_DISCLAIMER),
        created_at=result.get("created_at"),
        interpretation_id=result.get("interpretation_id"),
    )


# ---------------------------------------------------------------------------
# Contracts.2 — GET /{upload_id}/reviews
# ---------------------------------------------------------------------------
@router.get(
    "/{upload_id}/reviews",
    response_model=ContractReviewListPage,
    summary="List past contract reviews (published Document artifacts)",
)
async def list_reviews_route(
    upload_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user_or_agent),  # noqa: ARG001
) -> ContractReviewListPage:
    contract = await contracts_service.get_status(db, upload_id)
    if contract is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "contract not found")

    items_raw = await contracts_service.list_reviews(db, upload_id=upload_id, limit=limit)
    items = [
        ContractReviewListItem(
            review_artifact_id=r["review_artifact_id"],
            created_at=r["created_at"],
            severity_counts=ContractReviewSeverityCounts(**r["severity_counts"]),
        )
        for r in items_raw
    ]
    return ContractReviewListPage(items=items, total=len(items))


# ---------------------------------------------------------------------------
# Contracts.2 — GET /{upload_id}/interpretations
# ---------------------------------------------------------------------------
@router.get(
    "/{upload_id}/interpretations",
    response_model=ContractInterpretationListPage,
    summary="Q&A history for a contract",
)
async def list_interpretations_route(
    upload_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user_or_agent),  # noqa: ARG001
) -> ContractInterpretationListPage:
    contract = await contracts_service.get_status(db, upload_id)
    if contract is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "contract not found")

    rows, total = await contracts_service.list_interpretations(
        db, upload_id=upload_id, limit=limit
    )
    items = [
        ContractInterpretationOut(
            contract_upload_id=upload_id,
            question=r.question,
            answer=r.answer_json.get("answer", ""),
            supporting_clauses=r.answer_json.get("supporting_clauses", []),
            confidence=r.answer_json.get("confidence", 0.0),
            caveats=r.answer_json.get("caveats", []),
            disclaimer=r.answer_json.get("disclaimer", _CONTRACT_DISCLAIMER),
            created_at=r.created_at,
            interpretation_id=r.id,
        )
        for r in rows
    ]
    return ContractInterpretationListPage(items=items, total=total)


# ---------------------------------------------------------------------------
# Contracts.3 — POST /draft
# ---------------------------------------------------------------------------
@router.post(
    "/draft",
    response_model=ContractOut,
    status_code=http_status.HTTP_201_CREATED,
    summary="Create a new AI-drafted contract request",
)
async def create_draft_route(
    body: ContractDraftRequest,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> ContractOut:
    """Passkey-gated. Creates a Contract row with source='drafted', status='drafting'."""
    from app.services.contracts import service as _contracts_service

    contract = await _contracts_service.create_draft_request(db, request=body, user=user)
    return _to_out(contract)


# ---------------------------------------------------------------------------
# Contracts.3 — POST /{upload_id}/dispatch_draft
# ---------------------------------------------------------------------------
class _DispatchDraftOut(BaseModel):
    ok: bool
    upload_id: str
    audit_hash: str


@router.post(
    "/{upload_id}/dispatch_draft",
    response_model=_DispatchDraftOut,
    summary="Request contract-drafter agent dispatch",
)
async def dispatch_draft_route(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> _DispatchDraftOut:
    """Signal that the contract-draft-dispatcher should pick up this contract.

    - 404 if not found.
    - 409 if status not in (drafting, failed) or source != 'drafted'.
    """
    _DRAFT_DISPATCH_STATUSES = {"drafting", "failed"}

    contract = await contracts_service.get_status(db, upload_id)
    if contract is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "contract not found")
    if contract.source != "drafted":
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "contract source is not 'drafted'; dispatch_draft only applies to AI-drafted contracts",
        )
    if contract.status not in _DRAFT_DISPATCH_STATUSES:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            f"contract is not in a dispatchable status (current: {contract.status}); "
            f"must be one of {sorted(_DRAFT_DISPATCH_STATUSES)}",
        )

    # Write a priority marker for the draft dispatcher.
    try:
        repo_root = Path(__file__).resolve().parents[3]
        marker_dir = repo_root / "_state" / "contract_draft_requests"
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker_file = marker_dir / f"{upload_id}.json"
        marker_file.write_text(
            json.dumps(
                {
                    "upload_id": upload_id,
                    "requested_at": datetime.now(UTC).isoformat(),
                    "requested_by": getattr(user, "id", str(user)),
                }
            ),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        import logging as _logging
        _logging.getLogger("quill.contracts").warning(
            "dispatch_draft.marker_write_failed upload_id=%s err=%s", upload_id, exc
        )

    entry = await audit_svc.record_event(
        db,
        event_type="contract.draft_dispatch_requested",
        actor=getattr(user, "id", "system"),
        approval_item_id=None,
        payload={"upload_id": upload_id, "contract_id": contract.id},
    )
    await db.commit()

    return _DispatchDraftOut(ok=True, upload_id=upload_id, audit_hash=entry.hash)


# ---------------------------------------------------------------------------
# Contracts.3 — POST /{upload_id}/redraft
# ---------------------------------------------------------------------------
@router.post(
    "/{upload_id}/redraft",
    response_model=ContractOut,
    status_code=http_status.HTTP_201_CREATED,
    summary="Create a revised draft from an existing contract",
)
async def redraft_route(
    upload_id: str,
    body: RedraftRequest,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> ContractOut:
    """Passkey-gated. Creates a new Contract row derived from the parent."""
    from app.services.contracts import service as _contracts_service

    try:
        contract = await _contracts_service.request_redraft(
            db,
            parent_upload_id=upload_id,
            revision_notes=body.revision_notes,
            key_terms_overrides=body.key_terms_overrides,
            user=user,
        )
    except LookupError as e:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, str(e)) from e
    except ValueError as e:
        raise HTTPException(http_status.HTTP_409_CONFLICT, str(e)) from e

    return _to_out(contract)