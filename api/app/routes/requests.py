"""Requests routes — unified project submission interface (Requests tab).

Endpoints:
  POST  /v1/requests        — submit a project request (text + optional files)
  GET   /v1/requests        — list request history for the current user
  GET   /v1/requests/{id}   — get a single request by ID
  PATCH /v1/requests/{id}   — update request status/response (agent service account)

Intent classification (keyword-based, MVP):
  - estimate  → Estimates module
  - schedule  → Schedules module
  - rfi       → RFI module
  - contract  → Contracts module
  - general   → general / TBD

Dispatch:
  After creating a request record, a marker file is written to
  ``_state/request_dispatch_requests/{request_id}.json``.  An external
  coordinator agent picks up the marker, calls the appropriate Quill agent,
  and calls PATCH /v1/requests/{id} (using X-Agent-Secret) to store the
  response and flip status to complete/failed.

Auth: Bearer JWT (same as all other routes) + X-Agent-Secret for PATCH.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Optional

import json
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models_requests import RequestRecord
from app.security import get_current_user, require_agent_secret

_settings = get_settings()

INTERNAL_API_URL: str = _settings.INTERNAL_API_URL
DATASITE_URL: str = _settings.DATASITE_URL

AGENT_DISPATCH_MAP: dict[str, str] = {
    "estimate": f"{INTERNAL_API_URL}/v1/agents/estimate",
    "rfi": f"{INTERNAL_API_URL}/v1/agents/rfi",
    "contract": f"{INTERNAL_API_URL}/v1/agents/contract",
    "general": f"{INTERNAL_API_URL}/v1/agents/coordinator",
    "site_evaluation": f"{DATASITE_URL}/sites/questionnaire",
}

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


class RequestUpdateIn(BaseModel):
    """Payload for PATCH /v1/requests/{request_id} (agent service account)."""

    status: str  # complete | failed
    response: Optional[str] = None
    output_module: Optional[str] = None  # estimates | schedules | rfi | contracts
    output_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Dispatch helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REQUEST_DISPATCH_DIR = _REPO_ROOT / "_state" / "request_dispatch_requests"


async def _dispatch_to_agent(
    request_id: str,
    intent: str,
    message: str,
    filenames: list[str],
    drive_url: str | None,
    user_id: str,
) -> None:
    """Async HTTP dispatcher — posts to the appropriate agent endpoint.

    On success: calls PATCH /v1/requests/{id} internally to store the response.
    On failure: marks the request as failed with the error message.
    Wraps everything in try/except so a dispatch failure never crashes the caller.
    """
    import os
    from app.db import SessionLocal as async_session_maker  # noqa: N812

    # site_evaluation intent from a plain-text message cannot be dispatched directly
    # to DataSite's /sites/questionnaire endpoint (requires a deeply structured body).
    # Instead, return a guided response directing the user to the /sites/new form,
    # preserving their message as context.
    if intent == "site_evaluation":
        try:
            async with async_session_maker() as session:
                record = await session.get(RequestRecord, request_id)
                if record is not None:
                    record.status = "complete"
                    record.response = (
                        f"To evaluate a site, please use the **Sites** tab and click **New Site** "
                        f"to fill out the structured evaluation form. This ensures all scoring "
                        f"criteria (power, fiber, permitting, environmental, etc.) are captured "
                        f"accurately.\n\n"
                        f"Your request has been saved: \"{message[:200]}\""
                    )
                    record.output_module = "sites"
                    record.updated_at = _utcnow()
                    await session.commit()
                    log.info("dispatch.site_eval_guided request_id=%s", request_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("dispatch.site_eval_guide_failed request_id=%s err=%s", request_id, exc)
        return

    endpoint = AGENT_DISPATCH_MAP.get(intent, AGENT_DISPATCH_MAP["general"])
    payload = {
        "request_id": request_id,
        "intent": intent,
        "message": message,
        "filenames": filenames,
        "drive_url": drive_url,
        "user_id": user_id,
        "requested_at": _utcnow().isoformat(),
    }

    new_status = "failed"
    response_text: str | None = None

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(endpoint, json=payload)
            if resp.status_code < 400:
                new_status = "complete"
                try:
                    body = resp.json()
                    # If agent returns a stub / not-implemented marker, treat as processing
                    if isinstance(body, dict) and body.get("status") == "agent_not_implemented":
                        new_status = "processing"
                        response_text = "Agent not yet implemented — request queued."
                    else:
                        response_text = json.dumps(body) if not isinstance(body, str) else body
                except Exception:
                    response_text = resp.text[:2000]
            else:
                response_text = f"Agent returned {resp.status_code}: {resp.text[:500]}"
                new_status = "failed"
    except httpx.ConnectError as exc:
        log.warning("dispatch.connect_error request_id=%s endpoint=%s err=%s", request_id, endpoint, exc)
        response_text = f"Agent unreachable ({endpoint}): {exc}"
        new_status = "failed"
    except Exception as exc:  # noqa: BLE001
        log.exception("dispatch.unexpected_error request_id=%s", request_id)
        response_text = f"Unexpected dispatch error: {exc}"
        new_status = "failed"

    # Skip DB update for processing state (agent will call PATCH when done)
    if new_status == "processing":
        log.info("dispatch.queued request_id=%s intent=%s", request_id, intent)
        # Still write the marker file as a backup for the external coordinator
        _write_dispatch_marker(request_id, intent, message, filenames, drive_url, user_id)
        return

    # Update the DB record directly (same process, share DB session)
    try:
        # Use a fresh session since we're in a background task
        async with async_session_maker() as session:
            record = await session.get(RequestRecord, request_id)
            if record is not None:
                record.status = new_status
                record.response = response_text
                record.updated_at = _utcnow()
                await session.commit()
                log.info(
                    "dispatch.complete request_id=%s status=%s",
                    request_id,
                    new_status,
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("dispatch.db_update_failed request_id=%s err=%s", request_id, exc)


def _write_dispatch_marker(
    request_id: str,
    intent: str,
    message: str,
    filenames: list[str],
    drive_url: str | None,
    user_id: str,
) -> None:
    """Write a JSON marker file for the external coordinator to pick up.

    Non-fatal: if the write fails the request is still accepted — the external
    coordinator can also poll ``project_requests`` for records stuck in
    ``processing`` status.
    """
    try:
        _REQUEST_DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
        marker_path = _REQUEST_DISPATCH_DIR / f"{request_id}.json"
        marker_path.write_text(
            json.dumps(
                {
                    "request_id": request_id,
                    "intent": intent,
                    "message": message,
                    "filenames": filenames,
                    "drive_url": drive_url,
                    "user_id": user_id,
                    "requested_at": _utcnow().isoformat(),
                }
            ),
            encoding="utf-8",
        )
        log.info("dispatch marker written request_id=%s intent=%s", request_id, intent)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "dispatch_marker.write_failed request_id=%s err=%s", request_id, exc
        )
        # Non-fatal — coordinator can poll project_requests for stuck records.


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

def classify_intent(message: str, filenames: list[str]) -> str:
    """Keyword-based intent classification. Returns one of:
    estimate | schedule | rfi | contract | site_evaluation | general
    """
    text = (message + " " + " ".join(filenames)).lower()

    # site_evaluation — check before general keywords to avoid false positives
    if any(w in text for w in ["evaluate site", "data center site", "go/no-go", "parcel", "site evaluation", "site evaluator"]):
        return "site_evaluation"
    # "site" alone is checked after more specific terms to reduce false positives
    # Only treat bare "site" as site_evaluation when accompanied by evaluation context
    if "site" in text and any(w in text for w in ["score", "feasibility", "data center potential", "hpc", "hyperscale", "colocation"]):
        return "site_evaluation"
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
        "site_evaluation": "Site Evaluator",
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
    intent_override: Optional[str] = Form(
        default=None,
        alias="intent",
        description="Optional intent override; skips auto-classification when provided.",
    ),
    background_tasks: BackgroundTasks = BackgroundTasks(),
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

    If ``intent`` is provided in the form payload and matches a known value,
    it overrides keyword-based auto-classification.
    """
    _VALID_INTENTS = {"estimate", "schedule", "rfi", "contract", "general", "site_evaluation"}
    file_names = [f.filename or "" for f in files if f.filename]
    if intent_override and intent_override in _VALID_INTENTS:
        intent = intent_override
    else:
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

    # Dispatch to agent via async HTTP (with marker-file fallback for queued state).
    background_tasks.add_task(
        _dispatch_to_agent,
        request_id=record.id,
        intent=intent,
        message=message,
        filenames=file_names,
        drive_url=drive_url or None,
        user_id=str(user.id),
    )

    agent_label = _intent_label(intent)
    return RequestSubmitResponse(
        request_id=record.id,
        intent=intent,
        status="processing",
        message=f"Routing to {agent_label}…",
    )


# ---------------------------------------------------------------------------
# PATCH /v1/requests/{request_id} — agent service account callback
# ---------------------------------------------------------------------------


@router.patch(
    "/{request_id}",
    response_model=RequestOut,
    summary="Update request status/response (agent service account only)",
)
async def update_request(
    request_id: str,
    body: RequestUpdateIn,
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(require_agent_secret),
) -> RequestOut:
    """Called by the external coordinator agent after processing a request.

    Accepts only status values ``complete`` or ``failed``.
    Authenticated via X-Agent-Secret header.
    """
    record = await db.get(RequestRecord, request_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "request not found")

    allowed_statuses = {"complete", "failed"}
    if body.status not in allowed_statuses:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"status must be one of {sorted(allowed_statuses)}",
        )

    record.status = body.status
    record.updated_at = _utcnow()
    if body.response is not None:
        record.response = body.response
    if body.output_module is not None:
        record.output_module = body.output_module
    if body.output_id is not None:
        record.output_id = body.output_id

    await db.commit()
    await db.refresh(record)

    log.info(
        "request updated id=%s status=%s output_module=%s",
        request_id,
        body.status,
        body.output_module,
    )
    return RequestOut.model_validate(record)


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
