"""Contracts HTTP surface — Sprint Contracts.1.

POST   /v1/contracts/upload                         multipart, returns upload_id
GET    /v1/contracts                                list with optional filters
GET    /v1/contracts/{upload_id}                    full record
GET    /v1/contracts/{upload_id}/status             lightweight status
POST   /v1/contracts/{upload_id}/dispatch_extraction schedule agent extraction
POST   /v1/contracts/{upload_id}/cancel             idempotent cancel
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
    _CONTRACT_DISCLAIMER,
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
