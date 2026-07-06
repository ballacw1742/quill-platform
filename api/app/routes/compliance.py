"""Compliance Register routes — Sprint 4A

Division 8 — Contract obligations, regulatory filings, insurance policies,
and compliance checklists (SOC 2, ISO 27001, FISMA, NIST).

Endpoints:
  POST   /v1/compliance/obligations              — add contract obligation
  GET    /v1/compliance/obligations              — list obligations (?status=, ?contract_id=)
  PATCH  /v1/compliance/obligations/{id}         — update obligation

  POST   /v1/compliance/regulatory               — add regulatory deadline
  GET    /v1/compliance/regulatory               — list regulatory items (?jurisdiction=, ?status=)
  PATCH  /v1/compliance/regulatory/{id}          — update status

  POST   /v1/compliance/insurance                — add insurance policy
  GET    /v1/compliance/insurance                — list policies (?status=)
  PATCH  /v1/compliance/insurance/{id}           — update policy

  POST   /v1/compliance/checklists               — create compliance checklist
  GET    /v1/compliance/checklists               — list checklists
  GET    /v1/compliance/checklists/{id}          — get checklist with items
  PATCH  /v1/compliance/checklists/{id}/items/{item_id} — check/uncheck item

  GET    /v1/compliance/summary                  — portfolio compliance health summary
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from app.rate_limit import GET_LIMIT, POST_LIMIT, limiter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Contract
from app.models_compliance import (
    VALID_CHECKLIST_FRAMEWORKS,
    VALID_CHECKLIST_STATUSES,
    VALID_INSURANCE_STATUSES,
    VALID_INSURANCE_TYPES,
    VALID_OBLIGATION_STATUSES,
    VALID_OBLIGATION_TYPES,
    VALID_RECURRENCES,
    VALID_REGULATORY_FRAMEWORKS,
    VALID_REGULATORY_STATUSES,
    ComplianceChecklist,
    ComplianceChecklistItem,
    ContractObligation,
    InsurancePolicy,
    RegulatoryItem,
)
from app.security import get_current_user

log = logging.getLogger("quill.compliance")

router = APIRouter(prefix="/v1/compliance", tags=["compliance"])


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return datetime.now(UTC).date()


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────────────────────────


class ObligationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    contract_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    obligation_type: str
    due_date: Optional[date] = None
    recurrence: Optional[str] = None
    status: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ObligationIn(BaseModel):
    contract_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    obligation_type: str = "other"
    due_date: Optional[date] = None
    recurrence: Optional[str] = None
    status: str = "open"
    notes: Optional[str] = None


class ObligationPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    obligation_type: Optional[str] = None
    due_date: Optional[date] = None
    recurrence: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class ObligationListPage(BaseModel):
    items: List[ObligationOut]
    total: int
    limit: int
    offset: int


class RegulatoryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: Optional[str] = None
    framework: str
    jurisdiction: Optional[str] = None
    due_date: Optional[date] = None
    recurrence: Optional[str] = None
    status: str
    responsible_party: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class RegulatoryItemIn(BaseModel):
    title: str
    description: Optional[str] = None
    framework: str = "other"
    jurisdiction: Optional[str] = None
    due_date: Optional[date] = None
    recurrence: Optional[str] = None
    status: str = "open"
    responsible_party: Optional[str] = None
    notes: Optional[str] = None


class RegulatoryItemPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    framework: Optional[str] = None
    jurisdiction: Optional[str] = None
    due_date: Optional[date] = None
    recurrence: Optional[str] = None
    status: Optional[str] = None
    responsible_party: Optional[str] = None
    notes: Optional[str] = None


class RegulatoryListPage(BaseModel):
    items: List[RegulatoryItemOut]
    total: int
    limit: int
    offset: int


class InsurancePolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    policy_name: str
    policy_type: str
    carrier: Optional[str] = None
    policy_number: Optional[str] = None
    coverage_amount_usd: Optional[float] = None
    premium_annual_usd: Optional[float] = None
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    status: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class InsurancePolicyIn(BaseModel):
    policy_name: str
    policy_type: str = "other"
    carrier: Optional[str] = None
    policy_number: Optional[str] = None
    coverage_amount_usd: Optional[float] = None
    premium_annual_usd: Optional[float] = None
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    status: str = "active"
    notes: Optional[str] = None


class InsurancePolicyPatch(BaseModel):
    policy_name: Optional[str] = None
    policy_type: Optional[str] = None
    carrier: Optional[str] = None
    policy_number: Optional[str] = None
    coverage_amount_usd: Optional[float] = None
    premium_annual_usd: Optional[float] = None
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class InsuranceListPage(BaseModel):
    items: List[InsurancePolicyOut]
    total: int
    limit: int
    offset: int


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    checklist_id: str
    control_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    checked: bool
    checked_at: Optional[datetime] = None
    evidence_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ChecklistItemIn(BaseModel):
    control_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    checked: bool = False
    evidence_url: Optional[str] = None
    notes: Optional[str] = None


class ChecklistItemPatch(BaseModel):
    checked: Optional[bool] = None
    evidence_url: Optional[str] = None
    notes: Optional[str] = None


class ChecklistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    framework: str
    campus_id: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime


class ChecklistWithItemsOut(BaseModel):
    id: str
    name: str
    framework: str
    campus_id: Optional[str] = None
    status: str
    items: List[ChecklistItemOut]
    total_items: int
    checked_items: int
    created_at: datetime
    updated_at: datetime


class ChecklistIn(BaseModel):
    name: str
    framework: str = "custom"
    campus_id: Optional[str] = None
    status: str = "active"
    items: Optional[List[ChecklistItemIn]] = None  # optional seed items


class ChecklistListPage(BaseModel):
    items: List[ChecklistOut]
    total: int
    limit: int
    offset: int


class UpcomingDeadline(BaseModel):
    deadline_type: str  # "obligation" | "regulatory" | "insurance"
    id: str
    title: str
    due_date: Optional[date]
    days_until_due: Optional[int]
    status: str
    framework_or_type: str


class ComplianceSummaryOut(BaseModel):
    overdue_obligations: int
    expiring_insurance_30d: int
    open_regulatory_items: int
    checklists_complete_pct: float
    upcoming_deadlines: List[UpcomingDeadline]


class UpcomingDeadlineItem(BaseModel):
    source: str  # "checklist" | "contract"
    id: str
    title: str
    due_date: Optional[date]
    status: str


class UpcomingDeadlinesOut(BaseModel):
    items: List[UpcomingDeadlineItem]
    total: int


# ─────────────────────────────────────────────────────────────────────────────
# Obligations
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/obligations",
    response_model=ObligationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a contract obligation",
)
@limiter.limit(POST_LIMIT)  # Sprint 5.3 — create/submit: 30/min per IP
async def create_obligation(
    request: Request,
    body: ObligationIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> ObligationOut:
    if body.obligation_type not in VALID_OBLIGATION_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid obligation_type; must be one of {VALID_OBLIGATION_TYPES}",
        )
    if body.status not in VALID_OBLIGATION_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid status; must be one of {VALID_OBLIGATION_STATUSES}",
        )
    if body.recurrence and body.recurrence not in VALID_RECURRENCES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid recurrence; must be one of {VALID_RECURRENCES}",
        )

    row = ContractObligation(
        contract_id=body.contract_id,
        title=body.title,
        description=body.description,
        obligation_type=body.obligation_type,
        due_date=body.due_date,
        recurrence=body.recurrence,
        status=body.status,
        notes=body.notes,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ObligationOut.model_validate(row)


@router.get(
    "/obligations",
    response_model=ObligationListPage,
    summary="List contract obligations",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def list_obligations(
    request: Request,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    contract_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> ObligationListPage:
    q = select(ContractObligation)
    if status_filter:
        q = q.where(ContractObligation.status == status_filter)
    if contract_id:
        q = q.where(ContractObligation.contract_id == contract_id)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.order_by(ContractObligation.due_date.asc().nulls_last(), ContractObligation.created_at.desc())
    q = q.limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()

    return ObligationListPage(
        items=[ObligationOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch(
    "/obligations/{obligation_id}",
    response_model=ObligationOut,
    summary="Update an obligation",
)
async def update_obligation(
    obligation_id: str,
    body: ObligationPatch,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> ObligationOut:
    row = await db.get(ContractObligation, obligation_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "obligation not found")

    if body.obligation_type is not None and body.obligation_type not in VALID_OBLIGATION_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid obligation_type; must be one of {VALID_OBLIGATION_TYPES}",
        )
    if body.status is not None and body.status not in VALID_OBLIGATION_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid status; must be one of {VALID_OBLIGATION_STATUSES}",
        )

    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(row, field, val)
    row.updated_at = _utcnow()
    await db.commit()
    await db.refresh(row)
    return ObligationOut.model_validate(row)


# ─────────────────────────────────────────────────────────────────────────────
# Regulatory items
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/regulatory",
    response_model=RegulatoryItemOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a regulatory deadline",
)
@limiter.limit(POST_LIMIT)  # Sprint 5.3 — create/submit: 30/min per IP
async def create_regulatory_item(
    request: Request,
    body: RegulatoryItemIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> RegulatoryItemOut:
    if body.framework not in VALID_REGULATORY_FRAMEWORKS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid framework; must be one of {VALID_REGULATORY_FRAMEWORKS}",
        )
    if body.status not in VALID_REGULATORY_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid status; must be one of {VALID_REGULATORY_STATUSES}",
        )

    row = RegulatoryItem(
        title=body.title,
        description=body.description,
        framework=body.framework,
        jurisdiction=body.jurisdiction,
        due_date=body.due_date,
        recurrence=body.recurrence,
        status=body.status,
        responsible_party=body.responsible_party,
        notes=body.notes,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return RegulatoryItemOut.model_validate(row)


@router.get(
    "/regulatory",
    response_model=RegulatoryListPage,
    summary="List regulatory items",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def list_regulatory_items(
    request: Request,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    jurisdiction: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> RegulatoryListPage:
    q = select(RegulatoryItem)
    if status_filter:
        q = q.where(RegulatoryItem.status == status_filter)
    if jurisdiction:
        q = q.where(RegulatoryItem.jurisdiction == jurisdiction)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.order_by(RegulatoryItem.due_date.asc().nulls_last(), RegulatoryItem.created_at.desc())
    q = q.limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()

    return RegulatoryListPage(
        items=[RegulatoryItemOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch(
    "/regulatory/{regulatory_id}",
    response_model=RegulatoryItemOut,
    summary="Update a regulatory item",
)
async def update_regulatory_item(
    regulatory_id: str,
    body: RegulatoryItemPatch,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> RegulatoryItemOut:
    row = await db.get(RegulatoryItem, regulatory_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "regulatory item not found")

    if body.framework is not None and body.framework not in VALID_REGULATORY_FRAMEWORKS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid framework; must be one of {VALID_REGULATORY_FRAMEWORKS}",
        )
    if body.status is not None and body.status not in VALID_REGULATORY_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid status; must be one of {VALID_REGULATORY_STATUSES}",
        )

    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(row, field, val)
    row.updated_at = _utcnow()
    await db.commit()
    await db.refresh(row)
    return RegulatoryItemOut.model_validate(row)


# ─────────────────────────────────────────────────────────────────────────────
# Insurance policies
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/insurance",
    response_model=InsurancePolicyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add an insurance policy",
)
@limiter.limit(POST_LIMIT)  # Sprint 5.3 — create/submit: 30/min per IP
async def create_insurance_policy(
    request: Request,
    body: InsurancePolicyIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> InsurancePolicyOut:
    if body.policy_type not in VALID_INSURANCE_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid policy_type; must be one of {VALID_INSURANCE_TYPES}",
        )
    if body.status not in VALID_INSURANCE_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid status; must be one of {VALID_INSURANCE_STATUSES}",
        )

    row = InsurancePolicy(
        policy_name=body.policy_name,
        policy_type=body.policy_type,
        carrier=body.carrier,
        policy_number=body.policy_number,
        coverage_amount_usd=body.coverage_amount_usd,
        premium_annual_usd=body.premium_annual_usd,
        effective_date=body.effective_date,
        expiry_date=body.expiry_date,
        status=body.status,
        notes=body.notes,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return InsurancePolicyOut.model_validate(row)


@router.get(
    "/insurance",
    response_model=InsuranceListPage,
    summary="List insurance policies",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def list_insurance_policies(
    request: Request,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> InsuranceListPage:
    q = select(InsurancePolicy)
    if status_filter:
        q = q.where(InsurancePolicy.status == status_filter)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.order_by(InsurancePolicy.expiry_date.asc().nulls_last(), InsurancePolicy.created_at.desc())
    q = q.limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()

    return InsuranceListPage(
        items=[InsurancePolicyOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch(
    "/insurance/{policy_id}",
    response_model=InsurancePolicyOut,
    summary="Update an insurance policy",
)
async def update_insurance_policy(
    policy_id: str,
    body: InsurancePolicyPatch,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> InsurancePolicyOut:
    row = await db.get(InsurancePolicy, policy_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "insurance policy not found")

    if body.policy_type is not None and body.policy_type not in VALID_INSURANCE_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid policy_type; must be one of {VALID_INSURANCE_TYPES}",
        )
    if body.status is not None and body.status not in VALID_INSURANCE_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid status; must be one of {VALID_INSURANCE_STATUSES}",
        )

    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(row, field, val)
    row.updated_at = _utcnow()
    await db.commit()
    await db.refresh(row)
    return InsurancePolicyOut.model_validate(row)


# ─────────────────────────────────────────────────────────────────────────────
# Compliance checklists
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/checklists",
    response_model=ChecklistOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a compliance checklist",
)
@limiter.limit(POST_LIMIT)  # Sprint 5.3 — create/submit: 30/min per IP
async def create_checklist(
    request: Request,
    body: ChecklistIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> ChecklistOut:
    if body.framework not in VALID_CHECKLIST_FRAMEWORKS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid framework; must be one of {VALID_CHECKLIST_FRAMEWORKS}",
        )
    if body.status not in VALID_CHECKLIST_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid status; must be one of {VALID_CHECKLIST_STATUSES}",
        )

    checklist = ComplianceChecklist(
        name=body.name,
        framework=body.framework,
        campus_id=body.campus_id,
        status=body.status,
    )
    db.add(checklist)
    await db.flush()  # get the id before adding items

    # Optionally seed items
    if body.items:
        for item_in in body.items:
            item = ComplianceChecklistItem(
                checklist_id=checklist.id,
                control_id=item_in.control_id,
                title=item_in.title,
                description=item_in.description,
                checked=item_in.checked,
                evidence_url=item_in.evidence_url,
                notes=item_in.notes,
            )
            db.add(item)

    await db.commit()
    await db.refresh(checklist)
    return ChecklistOut.model_validate(checklist)


@router.get(
    "/checklists",
    response_model=ChecklistListPage,
    summary="List compliance checklists",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def list_checklists(
    request: Request,
    framework: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> ChecklistListPage:
    q = select(ComplianceChecklist)
    if framework:
        q = q.where(ComplianceChecklist.framework == framework)
    if status_filter:
        q = q.where(ComplianceChecklist.status == status_filter)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.order_by(ComplianceChecklist.created_at.desc())
    q = q.limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()

    return ChecklistListPage(
        items=[ChecklistOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/checklists/{checklist_id}",
    response_model=ChecklistWithItemsOut,
    summary="Get checklist with all items",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def get_checklist(
    request: Request,
    checklist_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> ChecklistWithItemsOut:
    checklist = await db.get(ComplianceChecklist, checklist_id)
    if checklist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "checklist not found")

    items_q = (
        select(ComplianceChecklistItem)
        .where(ComplianceChecklistItem.checklist_id == checklist_id)
        .order_by(ComplianceChecklistItem.created_at.asc())
    )
    items = (await db.execute(items_q)).scalars().all()

    total_items = len(items)
    checked_items = sum(1 for i in items if i.checked)

    return ChecklistWithItemsOut(
        id=checklist.id,
        name=checklist.name,
        framework=checklist.framework,
        campus_id=checklist.campus_id,
        status=checklist.status,
        items=[ChecklistItemOut.model_validate(i) for i in items],
        total_items=total_items,
        checked_items=checked_items,
        created_at=checklist.created_at,
        updated_at=checklist.updated_at,
    )


@router.patch(
    "/checklists/{checklist_id}/items/{item_id}",
    response_model=ChecklistItemOut,
    summary="Check or uncheck a checklist item",
)
async def update_checklist_item(
    checklist_id: str,
    item_id: str,
    body: ChecklistItemPatch,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> ChecklistItemOut:
    # Confirm checklist exists
    checklist = await db.get(ComplianceChecklist, checklist_id)
    if checklist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "checklist not found")

    item = await db.get(ComplianceChecklistItem, item_id)
    if item is None or item.checklist_id != checklist_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "checklist item not found")

    updates = body.model_dump(exclude_unset=True)
    if "checked" in updates:
        item.checked = updates["checked"]
        item.checked_at = _utcnow() if updates["checked"] else None
    if "evidence_url" in updates:
        item.evidence_url = updates["evidence_url"]
    if "notes" in updates:
        item.notes = updates["notes"]
    item.updated_at = _utcnow()

    # Auto-update checklist status: if all items checked → complete; else active
    items_q = select(ComplianceChecklistItem).where(
        ComplianceChecklistItem.checklist_id == checklist_id
    )
    all_items = (await db.execute(items_q)).scalars().all()
    if all_items and all(i.checked for i in all_items):
        checklist.status = "complete"
    elif checklist.status == "complete":
        checklist.status = "active"
    checklist.updated_at = _utcnow()

    await db.commit()
    await db.refresh(item)
    return ChecklistItemOut.model_validate(item)


# ─────────────────────────────────────────────────────────────────────────────
# Compliance summary
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/summary",
    response_model=ComplianceSummaryOut,
    summary="Portfolio compliance health summary",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def get_compliance_summary(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> ComplianceSummaryOut:
    today = _today()
    expiry_threshold = today + timedelta(days=30)

    # 1. Overdue obligations
    overdue_q = select(func.count()).where(ContractObligation.status == "overdue")
    overdue_obligations = (await db.execute(overdue_q)).scalar_one()

    # 2. Insurance expiring within 30 days (status=active and expiry_date <= today+30)
    expiring_q = select(func.count()).where(
        InsurancePolicy.status == "active",
        InsurancePolicy.expiry_date != None,  # noqa: E711
        InsurancePolicy.expiry_date <= expiry_threshold,
    )
    expiring_insurance_30d = (await db.execute(expiring_q)).scalar_one()

    # 3. Open regulatory items (status=open or in_progress)
    open_reg_q = select(func.count()).where(
        RegulatoryItem.status.in_(["open", "in_progress"])
    )
    open_regulatory_items = (await db.execute(open_reg_q)).scalar_one()

    # 4. Checklists completion %
    all_items_count_q = select(func.count()).select_from(ComplianceChecklistItem)
    checked_items_count_q = select(func.count()).where(ComplianceChecklistItem.checked == True)  # noqa: E712
    total_items = (await db.execute(all_items_count_q)).scalar_one()
    checked_items = (await db.execute(checked_items_count_q)).scalar_one()
    checklists_complete_pct = round((checked_items / total_items * 100) if total_items > 0 else 0.0, 1)

    # 5. Upcoming deadlines (next 5 items across all types, sorted by due_date)
    deadlines: list[UpcomingDeadline] = []

    # Obligations with due_date
    obl_q = (
        select(ContractObligation)
        .where(
            ContractObligation.due_date != None,  # noqa: E711
            ContractObligation.status.in_(["open", "overdue"]),
        )
        .order_by(ContractObligation.due_date.asc())
        .limit(10)
    )
    for row in (await db.execute(obl_q)).scalars():
        days = (row.due_date - today).days if row.due_date else None
        deadlines.append(
            UpcomingDeadline(
                deadline_type="obligation",
                id=row.id,
                title=row.title,
                due_date=row.due_date,
                days_until_due=days,
                status=row.status,
                framework_or_type=row.obligation_type,
            )
        )

    # Regulatory items with due_date
    reg_q = (
        select(RegulatoryItem)
        .where(
            RegulatoryItem.due_date != None,  # noqa: E711
            RegulatoryItem.status.in_(["open", "in_progress"]),
        )
        .order_by(RegulatoryItem.due_date.asc())
        .limit(10)
    )
    for row in (await db.execute(reg_q)).scalars():
        days = (row.due_date - today).days if row.due_date else None
        deadlines.append(
            UpcomingDeadline(
                deadline_type="regulatory",
                id=row.id,
                title=row.title,
                due_date=row.due_date,
                days_until_due=days,
                status=row.status,
                framework_or_type=row.framework,
            )
        )

    # Insurance expiring soon
    ins_q = (
        select(InsurancePolicy)
        .where(
            InsurancePolicy.expiry_date != None,  # noqa: E711
            InsurancePolicy.status.in_(["active", "expiring"]),
        )
        .order_by(InsurancePolicy.expiry_date.asc())
        .limit(10)
    )
    for row in (await db.execute(ins_q)).scalars():
        days = (row.expiry_date - today).days if row.expiry_date else None
        deadlines.append(
            UpcomingDeadline(
                deadline_type="insurance",
                id=row.id,
                title=row.policy_name,
                due_date=row.expiry_date,
                days_until_due=days,
                status=row.status,
                framework_or_type=row.policy_type,
            )
        )

    # Sort and take top 5
    deadlines.sort(key=lambda d: (d.due_date is None, d.due_date or date.max))
    upcoming_deadlines = deadlines[:5]

    return ComplianceSummaryOut(
        overdue_obligations=overdue_obligations,
        expiring_insurance_30d=expiring_insurance_30d,
        open_regulatory_items=open_regulatory_items,
        checklists_complete_pct=checklists_complete_pct,
        upcoming_deadlines=upcoming_deadlines,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Upcoming deadlines (Sprint 5.1 — Contract obligations → Compliance deadlines)
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/upcoming",
    response_model=UpcomingDeadlinesOut,
    summary="Deadlines due within the next 30 days (obligations + contracts)",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def get_upcoming_deadlines(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # noqa: ARG001
) -> UpcomingDeadlinesOut:
    """Aggregate compliance deadlines falling within the next 30 days.

    Two sources, unified into a single sorted list:
      - "checklist": ContractObligation rows (the compliance register's
        deadline-bearing obligations). NOTE: the literal ComplianceChecklistItem
        model carries no due_date/status, so obligations are the checklist-side
        deadline source here — see the Sprint 5.1 report caveat.
      - "contract": Contract documents (from the contracts table) whose
        expiration_date falls in the window.

    Items are sorted by due_date ascending. Returns an empty list when nothing
    is due (e.g. no supply chain / contract data).
    """
    today = _today()
    horizon = today + timedelta(days=30)

    items: list[UpcomingDeadlineItem] = []

    # a) Compliance obligations with a due_date in [today, today+30]
    obl_q = select(ContractObligation).where(
        ContractObligation.due_date != None,  # noqa: E711
        ContractObligation.due_date >= today,
        ContractObligation.due_date <= horizon,
    )
    for row in (await db.execute(obl_q)).scalars():
        items.append(
            UpcomingDeadlineItem(
                source="checklist",
                id=row.id,
                title=row.title,
                due_date=row.due_date,
                status=row.status,
            )
        )

    # b) Contracts whose expiration_date falls in the window. expiration_date is a
    #    datetime; compare against day bounds and surface the date component.
    horizon_end = datetime.combine(horizon, datetime.max.time()).replace(tzinfo=UTC)
    today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=UTC)
    con_q = select(Contract).where(
        Contract.expiration_date != None,  # noqa: E711
        Contract.expiration_date >= today_start,
        Contract.expiration_date <= horizon_end,
    )
    for row in (await db.execute(con_q)).scalars():
        title = row.project_label or row.contract_type or "Untitled contract"
        items.append(
            UpcomingDeadlineItem(
                source="contract",
                id=row.id,
                title=title,
                due_date=row.expiration_date.date() if row.expiration_date else None,
                status=row.status,
            )
        )

    # Sort by due_date ascending (None last, though all here have a due_date).
    items.sort(key=lambda d: (d.due_date is None, d.due_date or date.max))

    return UpcomingDeadlinesOut(items=items, total=len(items))
