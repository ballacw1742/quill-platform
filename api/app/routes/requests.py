"""Requests routes — unified project submission interface (Requests tab).

Endpoints:
  POST  /v1/requests        — submit a project request (text + optional files)
  GET   /v1/requests        — list request history for the current user
  GET   /v1/requests/{id}   — get a single request by ID

Intent classification (keyword-based, MVP):
  - estimate  → Estimates module
  - schedule  → Schedules module
  - rfi       → RFI module
  - contract  → Contracts module
  - general   → general / TBD

Auth: Bearer JWT (same as all other routes).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models_requests import RequestRecord
from app.security import get_current_user

log = logging.getLogger("quill.requests")

router = APIRouter(prefix="/v1/requests", tags=["requests"])


# ---------------------------------------------------------------------------
# Schemas (local — not in global schemas.py to keep the diff scoped)
# ---------------------------------------------------------------------------

class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    message: str
    intent: str
    status: str
    response: Optional[str] = None
    output_module: Optional[str] = None
    output_id: Optional[str] = None
    drive_url: Optional[str] = None
    filenames: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class RequestListResponse(BaseModel):
    items: list[RequestOut]
    total: int
    limit: int
    offset: int


class RequestSubmitResponse(BaseModel):
    request_id: str
    intent: str
    status: str
    message: str


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

def classify_intent(message: str, filenames: list[str]) -> str:
    """Keyword-based intent classification. Returns one of:
    estimate | schedule | rfi | contract | general
    """
    text = (message + " " + " ".join(filenames)).lower()

    if any(w in text for w in ["estimate", "cost", "budget", "price", "bid", "scope", "takeoff", "quantity"]):
        return "estimate"
    if any(w in text for w in ["schedule", "timeline", "gantt", "critical path", "milestone", "sequenc", "duration"]):
        return "schedule"
    if any(w in text for w in ["rfi", "request for information", "clarification", "question", "submittal", "inquiry"]):
        return "rfi"
    if any(w in text for w in ["contract", "agreement", "subcontract", "clause", "terms", "conditions", "liability"]):
        return "contract"
    return "general"


def _intent_label(intent: str) -> str:
    labels = {
        "estimate": "Estimator",
        "schedule": "Scheduler",
        "rfi": "RFI Agent",
        "contract": "Contract Reviewer",
        "general": "Coordinator",
    }
    return labels.get(intent, "Agent")


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# POST /v1/requests
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=RequestSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a project request",
)
async def submit_request(
    message: str = Form(..., description="Describe your request"),
    files: list[UploadFile] = File(default=[]),
    drive_url: str = Form(default="", description="Optional Google Drive link"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> RequestSubmitResponse:
    """
    Submit a project request. The system classifies intent and routes to the
    appropriate agent. Results appear in the relevant module.

    Intent routing:
    - estimate  → co_estimator agent → Estimates module
    - schedule  → schedule_reader agent → Schedules module
    - rfi       → rfi_triage + rfi_drafter → RFI module
    - contract  → contract_reviewer → Contracts module
    - general   → coordinator agent
    """
    file_names = [f.filename or "" for f in files if f.filename]
    intent = classify_intent(message, file_names)
    filenames_str = ",".join(file_names) if file_names else None

    record = RequestRecord(
        user_id=str(user.id),
        message=message,
        intent=intent,
        status="processing",
        drive_url=drive_url or None,
        filenames=filenames_str,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    log.info(
        "request submitted user=%s intent=%s id=%s files=%d",
        user.id,
        intent,
        record.id,
        len(file_names),
    )

    agent_label = _intent_label(intent)
    return RequestSubmitResponse(
        request_id=record.id,
        intent=intent,
        status="processing",
        message=f"Routing to {agent_label}…",
    )


# ---------------------------------------------------------------------------
# GET /v1/requests
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=RequestListResponse,
    summary="List project request history for the current user",
)
async def list_requests(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> RequestListResponse:
    from sqlalchemy import func

    count_result = await db.execute(
        select(func.count()).select_from(RequestRecord).where(
            RequestRecord.user_id == str(user.id)
        )
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(RequestRecord)
        .where(RequestRecord.user_id == str(user.id))
        .order_by(RequestRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    records = result.scalars().all()

    return RequestListResponse(
        items=[RequestOut.model_validate(r) for r in records],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /v1/requests/{request_id}
# ---------------------------------------------------------------------------

@router.get(
    "/{request_id}",
    response_model=RequestOut,
    summary="Get a single project request",
)
async def get_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> RequestOut:
    record = await db.get(RequestRecord, request_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "request not found")
    if record.user_id != str(user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your request")
    return RequestOut.model_validate(record)
