"""Pipeline routes — Sprint 1B

Endpoints:
  POST  /v1/accounts                     — create account (prospect or customer)
  GET   /v1/accounts                     — list accounts (filter: ?type=)
  GET   /v1/accounts/{account_id}        — account detail
  PATCH /v1/accounts/{account_id}        — update account

  POST  /v1/deals                        — create deal
  GET   /v1/deals                        — list deals (filter: ?stage=, ?account_id=)
  GET   /v1/deals/{deal_id}              — deal detail (includes account)
  PATCH /v1/deals/{deal_id}              — update deal

  POST  /v1/deals/{deal_id}/activities   — log activity
  GET   /v1/deals/{deal_id}/activities   — activity history (newest first)

  GET   /v1/pipeline/summary             — pipeline summary: deals by stage with MW + value
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from app.rate_limit import GET_LIMIT, POST_LIMIT, limiter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models_pipeline import (
    Account,
    Deal,
    DealActivity,
    VALID_ACCOUNT_TYPES,
    VALID_ACTIVITY_TYPES,
    VALID_DEAL_STAGES,
    VALID_WORKLOAD_TYPES,
)
from app.security import get_current_user, get_current_user_or_agent

log = logging.getLogger("quill.pipeline")

router = APIRouter(tags=["pipeline"])

# Pipeline stage order for stepper display
STAGE_ORDER = ["prospect", "qualified", "proposal", "negotiating", "won", "lost"]
ACTIVE_STAGES = {"prospect", "qualified", "proposal", "negotiating"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Pydantic schemas (local to this module — pipeline-specific)
# ---------------------------------------------------------------------------

class AccountCreate(BaseModel):
    name: str
    type: str = "prospect"
    industry: Optional[str] = None
    website: Optional[str] = None
    hq_city: Optional[str] = None
    hq_state: Optional[str] = None
    primary_contact_name: Optional[str] = None
    primary_contact_email: Optional[str] = None
    primary_contact_phone: Optional[str] = None
    notes: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    hq_city: Optional[str] = None
    hq_state: Optional[str] = None
    primary_contact_name: Optional[str] = None
    primary_contact_email: Optional[str] = None
    primary_contact_phone: Optional[str] = None
    notes: Optional[str] = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: str
    industry: Optional[str]
    website: Optional[str]
    hq_city: Optional[str]
    hq_state: Optional[str]
    primary_contact_name: Optional[str]
    primary_contact_email: Optional[str]
    primary_contact_phone: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class AccountListPage(BaseModel):
    items: list[AccountOut]
    total: int


class DealCreate(BaseModel):
    account_id: str
    name: str
    stage: str = "prospect"
    value_usd: Optional[float] = None
    mw_required: Optional[float] = None
    workload_type: Optional[str] = None
    probability_pct: Optional[int] = None
    expected_close: Optional[date] = None
    campus_id: Optional[str] = None
    project_id: Optional[str] = None
    lost_reason: Optional[str] = None
    notes: Optional[str] = None


class DealUpdate(BaseModel):
    account_id: Optional[str] = None
    name: Optional[str] = None
    stage: Optional[str] = None
    value_usd: Optional[float] = None
    mw_required: Optional[float] = None
    workload_type: Optional[str] = None
    probability_pct: Optional[int] = None
    expected_close: Optional[date] = None
    campus_id: Optional[str] = None
    project_id: Optional[str] = None
    lost_reason: Optional[str] = None
    notes: Optional[str] = None


class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    name: str
    stage: str
    value_usd: Optional[float]
    mw_required: Optional[float]
    workload_type: Optional[str]
    probability_pct: Optional[int]
    expected_close: Optional[date]
    campus_id: Optional[str]
    project_id: Optional[str]
    lost_reason: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class DealWithAccountOut(DealOut):
    account: AccountOut


class DealListPage(BaseModel):
    items: list[DealOut]
    total: int


class ActivityCreate(BaseModel):
    activity_type: str
    summary: str
    created_by: Optional[str] = None


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    deal_id: str
    activity_type: str
    summary: str
    created_by: Optional[str]
    created_at: datetime


class ActivityListPage(BaseModel):
    items: list[ActivityOut]
    total: int


class StageStats(BaseModel):
    stage: str
    count: int
    total_mw: float
    total_value_usd: float


class PipelineSummaryOut(BaseModel):
    stages: list[StageStats]
    total_active_deals: int
    total_active_mw: float
    total_active_value_usd: float
    win_rate_pct: Optional[float]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_account_or_404(account_id: str, db: AsyncSession) -> Account:
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


async def _get_deal_or_404(deal_id: str, db: AsyncSession) -> Deal:
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


# ---------------------------------------------------------------------------
# Account routes
# ---------------------------------------------------------------------------

@router.post(
    "/v1/accounts",
    response_model=AccountOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create account",
)
@limiter.limit(POST_LIMIT)  # Sprint 5.3 — create/submit: 30/min per IP
async def create_account(
    request: Request,
    body: AccountCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    if body.type not in VALID_ACCOUNT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid account type. Must be one of: {', '.join(VALID_ACCOUNT_TYPES)}",
        )
    account = Account(
        name=body.name,
        type=body.type,
        industry=body.industry,
        website=body.website,
        hq_city=body.hq_city,
        hq_state=body.hq_state,
        primary_contact_name=body.primary_contact_name,
        primary_contact_email=body.primary_contact_email,
        primary_contact_phone=body.primary_contact_phone,
        notes=body.notes,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    log.info("account.created id=%s name=%s type=%s", account.id, account.name, account.type)
    return account


@router.get(
    "/v1/accounts",
    response_model=AccountListPage,
    summary="List accounts",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def list_accounts(
    request: Request,
    type: Optional[str] = Query(default=None, description="Filter by type: prospect|customer"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user_or_agent),
):
    q = select(Account)
    if type is not None:
        q = q.where(Account.type == type)
    q = q.order_by(Account.created_at.desc())

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    return AccountListPage(items=list(rows), total=total)


@router.get(
    "/v1/accounts/{account_id}",
    response_model=AccountOut,
    summary="Get account",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def get_account(
    request: Request,
    account_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user_or_agent),
):
    return await _get_account_or_404(account_id, db)


@router.patch(
    "/v1/accounts/{account_id}",
    response_model=AccountOut,
    summary="Update account",
)
async def update_account(
    account_id: str,
    body: AccountUpdate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    account = await _get_account_or_404(account_id, db)
    updates = body.model_dump(exclude_unset=True)
    if "type" in updates and updates["type"] not in VALID_ACCOUNT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid account type. Must be one of: {', '.join(VALID_ACCOUNT_TYPES)}",
        )
    for field, value in updates.items():
        setattr(account, field, value)
    account.updated_at = _utcnow()
    await db.commit()
    await db.refresh(account)
    return account


# ---------------------------------------------------------------------------
# Deal routes
# ---------------------------------------------------------------------------

@router.post(
    "/v1/deals",
    response_model=DealOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create deal",
)
@limiter.limit(POST_LIMIT)  # Sprint 5.3 — create/submit: 30/min per IP
async def create_deal(
    request: Request,
    body: DealCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    # Validate account exists
    await _get_account_or_404(body.account_id, db)

    if body.stage not in VALID_DEAL_STAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid stage. Must be one of: {', '.join(VALID_DEAL_STAGES)}",
        )
    if body.workload_type is not None and body.workload_type not in VALID_WORKLOAD_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid workload_type. Must be one of: {', '.join(VALID_WORKLOAD_TYPES)}",
        )
    deal = Deal(
        account_id=body.account_id,
        name=body.name,
        stage=body.stage,
        value_usd=body.value_usd,
        mw_required=body.mw_required,
        workload_type=body.workload_type,
        probability_pct=body.probability_pct,
        expected_close=body.expected_close,
        campus_id=body.campus_id,
        project_id=body.project_id,
        lost_reason=body.lost_reason,
        notes=body.notes,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(deal)
    await db.commit()
    await db.refresh(deal)
    log.info("deal.created id=%s name=%s stage=%s", deal.id, deal.name, deal.stage)
    return deal


@router.get(
    "/v1/deals",
    response_model=DealListPage,
    summary="List deals",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def list_deals(
    request: Request,
    stage: Optional[str] = Query(default=None),
    account_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user_or_agent),
):
    q = select(Deal)
    if stage is not None:
        q = q.where(Deal.stage == stage)
    if account_id is not None:
        q = q.where(Deal.account_id == account_id)
    q = q.order_by(Deal.created_at.desc())

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    return DealListPage(items=list(rows), total=total)


@router.get(
    "/v1/deals/{deal_id}",
    response_model=DealWithAccountOut,
    summary="Get deal (with account)",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def get_deal(
    request: Request,
    deal_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user_or_agent),
):
    deal = await _get_deal_or_404(deal_id, db)
    account = await _get_account_or_404(deal.account_id, db)
    return DealWithAccountOut(
        id=deal.id,
        account_id=deal.account_id,
        name=deal.name,
        stage=deal.stage,
        value_usd=deal.value_usd,
        mw_required=deal.mw_required,
        workload_type=deal.workload_type,
        probability_pct=deal.probability_pct,
        expected_close=deal.expected_close,
        campus_id=deal.campus_id,
        project_id=deal.project_id,
        lost_reason=deal.lost_reason,
        notes=deal.notes,
        created_at=deal.created_at,
        updated_at=deal.updated_at,
        account=AccountOut.model_validate(account),
    )


@router.patch(
    "/v1/deals/{deal_id}",
    response_model=DealOut,
    summary="Update deal",
)
async def update_deal(
    deal_id: str,
    body: DealUpdate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    deal = await _get_deal_or_404(deal_id, db)
    updates = body.model_dump(exclude_unset=True)

    if "stage" in updates and updates["stage"] not in VALID_DEAL_STAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid stage. Must be one of: {', '.join(VALID_DEAL_STAGES)}",
        )
    if "workload_type" in updates and updates["workload_type"] is not None and updates["workload_type"] not in VALID_WORKLOAD_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid workload_type. Must be one of: {', '.join(VALID_WORKLOAD_TYPES)}",
        )
    if "account_id" in updates:
        await _get_account_or_404(updates["account_id"], db)

    # When deal moves to Won, upgrade account type to customer
    if updates.get("stage") == "won":
        account = await _get_account_or_404(deal.account_id, db)
        if account.type == "prospect":
            account.type = "customer"
            account.updated_at = _utcnow()

    for field, value in updates.items():
        setattr(deal, field, value)
    deal.updated_at = _utcnow()
    await db.commit()
    await db.refresh(deal)
    log.info("deal.updated id=%s stage=%s", deal.id, deal.stage)
    return deal


# ---------------------------------------------------------------------------
# Activity routes
# ---------------------------------------------------------------------------

@router.post(
    "/v1/deals/{deal_id}/activities",
    response_model=ActivityOut,
    status_code=status.HTTP_201_CREATED,
    summary="Log activity on deal",
)
@limiter.limit(POST_LIMIT)  # Sprint 5.3 — create/submit: 30/min per IP
async def add_activity(
    request: Request,
    deal_id: str,
    body: ActivityCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    await _get_deal_or_404(deal_id, db)
    if body.activity_type not in VALID_ACTIVITY_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid activity_type. Must be one of: {', '.join(VALID_ACTIVITY_TYPES)}",
        )
    created_by = body.created_by or getattr(user, "email", None) or getattr(user, "id", None)
    activity = DealActivity(
        deal_id=deal_id,
        activity_type=body.activity_type,
        summary=body.summary,
        created_by=created_by,
        created_at=_utcnow(),
    )
    db.add(activity)
    await db.commit()
    await db.refresh(activity)
    log.info("activity.created id=%s deal_id=%s type=%s", activity.id, deal_id, activity.activity_type)
    return activity


@router.get(
    "/v1/deals/{deal_id}/activities",
    response_model=ActivityListPage,
    summary="List activities for deal (newest first)",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def list_activities(
    request: Request,
    deal_id: str,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user_or_agent),
):
    await _get_deal_or_404(deal_id, db)
    q = (
        select(DealActivity)
        .where(DealActivity.deal_id == deal_id)
        .order_by(DealActivity.created_at.desc())
    )

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    return ActivityListPage(items=list(rows), total=total)


# ---------------------------------------------------------------------------
# Pipeline summary
# ---------------------------------------------------------------------------

@router.get(
    "/v1/pipeline/summary",
    response_model=PipelineSummaryOut,
    summary="Pipeline summary: deals by stage with MW and value",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def pipeline_summary(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user_or_agent),
):
    # Per-stage aggregation
    stage_agg = await db.execute(
        select(
            Deal.stage,
            func.count(Deal.id).label("cnt"),
            func.coalesce(func.sum(Deal.mw_required), 0.0).label("total_mw"),
            func.coalesce(func.sum(Deal.value_usd), 0.0).label("total_value"),
        ).group_by(Deal.stage)
    )
    rows = stage_agg.all()

    stage_map: dict[str, StageStats] = {}
    for row in rows:
        stage_map[row.stage] = StageStats(
            stage=row.stage,
            count=row.cnt,
            total_mw=float(row.total_mw),
            total_value_usd=float(row.total_value),
        )

    # Fill missing stages with zeroes
    stages = [
        stage_map.get(s, StageStats(stage=s, count=0, total_mw=0.0, total_value_usd=0.0))
        for s in STAGE_ORDER
    ]

    # Active totals (exclude won/lost)
    total_active_deals = sum(s.count for s in stages if s.stage in ACTIVE_STAGES)
    total_active_mw = sum(s.total_mw for s in stages if s.stage in ACTIVE_STAGES)
    total_active_value = sum(s.total_value_usd for s in stages if s.stage in ACTIVE_STAGES)

    # Win rate
    won_count = stage_map.get("won", StageStats(stage="won", count=0, total_mw=0.0, total_value_usd=0.0)).count
    lost_count = stage_map.get("lost", StageStats(stage="lost", count=0, total_mw=0.0, total_value_usd=0.0)).count
    closed = won_count + lost_count
    win_rate = round((won_count / closed) * 100, 1) if closed > 0 else None

    return PipelineSummaryOut(
        stages=stages,
        total_active_deals=total_active_deals,
        total_active_mw=total_active_mw,
        total_active_value_usd=total_active_value,
        win_rate_pct=win_rate,
    )
