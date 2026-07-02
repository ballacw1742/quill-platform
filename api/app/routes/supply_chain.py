"""Supply Chain routes — Sprint 2B

Division 7 — Equipment procurement tracking for construction projects.
Surfaces long-lead item risks before they blow the construction schedule.

Endpoints:
  POST   /v1/equipment                      — add equipment item
  GET    /v1/equipment                      — list equipment (filter: ?project_id=, ?status=, ?category=, ?at_risk=true)
  GET    /v1/equipment/{equipment_id}       — get equipment detail
  PATCH  /v1/equipment/{equipment_id}       — update status/delivery date

  POST   /v1/vendors                        — add vendor
  GET    /v1/vendors                        — list vendors (filter: ?category=, ?prequalified=true)
  GET    /v1/vendors/{vendor_id}            — vendor detail
  PATCH  /v1/vendors/{vendor_id}            — update vendor

  GET    /v1/supply-chain/summary           — portfolio summary
  GET    /v1/supply-chain/at-risk           — all at-risk equipment
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models_supply_chain import (
    Equipment,
    Vendor,
    VALID_EQUIPMENT_CATEGORIES,
    VALID_EQUIPMENT_STATUSES,
    VALID_VENDOR_CATEGORIES,
)
from app.security import get_current_user

log = logging.getLogger("quill.supply_chain")

router = APIRouter(tags=["supply-chain"])

# At-risk thresholds
AT_RISK_BUFFER_DAYS = 30   # delivery projected this many days late = at risk
AT_RISK_TRANSIT_DAYS = 7   # in_transit items arriving within this window = at risk


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return datetime.now(UTC).date()


# ---------------------------------------------------------------------------
# At-risk computation — server-side only
# ---------------------------------------------------------------------------

def _is_at_risk(eq: Equipment) -> bool:
    """Return True if this equipment item is at risk of late delivery.

    Rules:
    1. status in (not_ordered, ordered) AND
       order_date + lead_time_weeks > today + AT_RISK_BUFFER_DAYS
    2. status == in_transit AND expected_delivery < today + AT_RISK_TRANSIT_DAYS
    """
    today = _today()

    if eq.status in ("not_ordered", "ordered"):
        if eq.order_date is not None and eq.lead_time_weeks is not None:
            projected = eq.order_date + timedelta(weeks=eq.lead_time_weeks)
            return projected > today + timedelta(days=AT_RISK_BUFFER_DAYS)
        # If we have no order date / lead time and it's not_ordered, treat cautiously
        # but don't flag — we don't have enough info.
        return False

    if eq.status == "in_transit":
        if eq.expected_delivery is not None:
            return eq.expected_delivery < today + timedelta(days=AT_RISK_TRANSIT_DAYS)
        return False

    return False


# ---------------------------------------------------------------------------
# Pydantic schemas (local to this module)
# ---------------------------------------------------------------------------

class EquipmentCreate(BaseModel):
    name: str
    category: str
    project_id: Optional[str] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    quantity: int = 1
    unit_cost_usd: Optional[float] = None
    lead_time_weeks: Optional[int] = None
    order_date: Optional[date] = None
    expected_delivery: Optional[date] = None
    actual_delivery: Optional[date] = None
    status: str = "not_ordered"
    vendor_id: Optional[str] = None
    notes: Optional[str] = None


class EquipmentUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    project_id: Optional[str] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    quantity: Optional[int] = None
    unit_cost_usd: Optional[float] = None
    lead_time_weeks: Optional[int] = None
    order_date: Optional[date] = None
    expected_delivery: Optional[date] = None
    actual_delivery: Optional[date] = None
    status: Optional[str] = None
    vendor_id: Optional[str] = None
    notes: Optional[str] = None


class EquipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: str
    project_id: Optional[str] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    quantity: int
    unit_cost_usd: Optional[float] = None
    lead_time_weeks: Optional[int] = None
    order_date: Optional[date] = None
    expected_delivery: Optional[date] = None
    actual_delivery: Optional[date] = None
    status: str
    vendor_id: Optional[str] = None
    notes: Optional[str] = None
    at_risk: bool = False
    total_cost_usd: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class EquipmentListResponse(BaseModel):
    items: list[EquipmentOut]
    total: int
    limit: int
    offset: int


class VendorCreate(BaseModel):
    name: str
    category: str
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    website: Optional[str] = None
    prequalified: bool = False
    performance_score: Optional[float] = None
    notes: Optional[str] = None


class VendorUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    website: Optional[str] = None
    prequalified: Optional[bool] = None
    performance_score: Optional[float] = None
    notes: Optional[str] = None


class VendorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: str
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    website: Optional[str] = None
    prequalified: bool
    performance_score: Optional[float] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class VendorListResponse(BaseModel):
    items: list[VendorOut]
    total: int
    limit: int
    offset: int


class SupplyChainSummary(BaseModel):
    total_equipment_items: int
    total_equipment_value_usd: float
    at_risk_count: int
    approved_vendor_count: int
    vendor_count: int


# ---------------------------------------------------------------------------
# Helper: enrich equipment with computed fields
# ---------------------------------------------------------------------------

def _enrich(eq: Equipment) -> EquipmentOut:
    total = (
        (eq.unit_cost_usd or 0.0) * eq.quantity
        if eq.unit_cost_usd is not None
        else None
    )
    return EquipmentOut(
        id=eq.id,
        name=eq.name,
        category=eq.category,
        project_id=eq.project_id,
        manufacturer=eq.manufacturer,
        model_number=eq.model_number,
        quantity=eq.quantity,
        unit_cost_usd=eq.unit_cost_usd,
        lead_time_weeks=eq.lead_time_weeks,
        order_date=eq.order_date,
        expected_delivery=eq.expected_delivery,
        actual_delivery=eq.actual_delivery,
        status=eq.status,
        vendor_id=eq.vendor_id,
        notes=eq.notes,
        at_risk=_is_at_risk(eq),
        total_cost_usd=total,
        created_at=eq.created_at,
        updated_at=eq.updated_at,
    )


# ---------------------------------------------------------------------------
# Equipment endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/v1/equipment",
    response_model=EquipmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add equipment item",
)
async def create_equipment(
    body: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> EquipmentOut:
    if body.category not in VALID_EQUIPMENT_CATEGORIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid category. Valid: {VALID_EQUIPMENT_CATEGORIES}",
        )
    if body.status not in VALID_EQUIPMENT_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid status. Valid: {VALID_EQUIPMENT_STATUSES}",
        )
    eq = Equipment(
        name=body.name,
        category=body.category,
        project_id=body.project_id,
        manufacturer=body.manufacturer,
        model_number=body.model_number,
        quantity=body.quantity,
        unit_cost_usd=body.unit_cost_usd,
        lead_time_weeks=body.lead_time_weeks,
        order_date=body.order_date,
        expected_delivery=body.expected_delivery,
        actual_delivery=body.actual_delivery,
        status=body.status,
        vendor_id=body.vendor_id,
        notes=body.notes,
    )
    db.add(eq)
    await db.commit()
    await db.refresh(eq)
    log.info("equipment.created id=%s name=%s user=%s", eq.id, eq.name, user.id)
    return _enrich(eq)


@router.get(
    "/v1/equipment",
    response_model=EquipmentListResponse,
    summary="List equipment",
)
async def list_equipment(
    project_id: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    category: Optional[str] = Query(default=None),
    at_risk: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> EquipmentListResponse:
    q = select(Equipment)
    if project_id:
        q = q.where(Equipment.project_id == project_id)
    if status_filter:
        q = q.where(Equipment.status == status_filter)
    if category:
        q = q.where(Equipment.category == category)
    q = q.order_by(Equipment.created_at.desc())

    total_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(total_q)).scalar_one()

    rows = (await db.execute(q.offset(offset).limit(limit))).scalars().all()

    items = [_enrich(eq) for eq in rows]

    # Filter at_risk server-side after enrichment
    if at_risk is True:
        items = [i for i in items if i.at_risk]
        total = len(items)  # recalculate for at_risk filter
    elif at_risk is False:
        items = [i for i in items if not i.at_risk]
        total = len(items)

    return EquipmentListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/v1/equipment/{equipment_id}",
    response_model=EquipmentOut,
    summary="Get equipment detail",
)
async def get_equipment(
    equipment_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> EquipmentOut:
    eq = await db.get(Equipment, equipment_id)
    if eq is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "equipment not found")
    return _enrich(eq)


@router.patch(
    "/v1/equipment/{equipment_id}",
    response_model=EquipmentOut,
    summary="Update equipment",
)
async def update_equipment(
    equipment_id: str,
    body: EquipmentUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> EquipmentOut:
    eq = await db.get(Equipment, equipment_id)
    if eq is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "equipment not found")

    updates = body.model_dump(exclude_unset=True)
    if "category" in updates and updates["category"] not in VALID_EQUIPMENT_CATEGORIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid category. Valid: {VALID_EQUIPMENT_CATEGORIES}",
        )
    if "status" in updates and updates["status"] not in VALID_EQUIPMENT_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid status. Valid: {VALID_EQUIPMENT_STATUSES}",
        )

    for k, v in updates.items():
        setattr(eq, k, v)
    eq.updated_at = _utcnow()

    await db.commit()
    await db.refresh(eq)
    log.info("equipment.updated id=%s user=%s", eq.id, user.id)
    return _enrich(eq)


# ---------------------------------------------------------------------------
# Vendor endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/v1/vendors",
    response_model=VendorOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add vendor",
)
async def create_vendor(
    body: VendorCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> VendorOut:
    if body.category not in VALID_VENDOR_CATEGORIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid category. Valid: {VALID_VENDOR_CATEGORIES}",
        )
    v = Vendor(
        name=body.name,
        category=body.category,
        contact_name=body.contact_name,
        contact_email=body.contact_email,
        contact_phone=body.contact_phone,
        website=body.website,
        prequalified=body.prequalified,
        performance_score=body.performance_score,
        notes=body.notes,
    )
    db.add(v)
    await db.commit()
    await db.refresh(v)
    log.info("vendor.created id=%s name=%s user=%s", v.id, v.name, user.id)
    return VendorOut.model_validate(v)


@router.get(
    "/v1/vendors",
    response_model=VendorListResponse,
    summary="List vendors",
)
async def list_vendors(
    category: Optional[str] = Query(default=None),
    prequalified: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> VendorListResponse:
    q = select(Vendor)
    if category:
        q = q.where(Vendor.category == category)
    if prequalified is not None:
        q = q.where(Vendor.prequalified == prequalified)
    q = q.order_by(Vendor.name.asc())

    total_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(total_q)).scalar_one()

    rows = (await db.execute(q.offset(offset).limit(limit))).scalars().all()
    return VendorListResponse(
        items=[VendorOut.model_validate(v) for v in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/v1/vendors/{vendor_id}",
    response_model=VendorOut,
    summary="Get vendor detail",
)
async def get_vendor(
    vendor_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> VendorOut:
    v = await db.get(Vendor, vendor_id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "vendor not found")
    return VendorOut.model_validate(v)


@router.patch(
    "/v1/vendors/{vendor_id}",
    response_model=VendorOut,
    summary="Update vendor",
)
async def update_vendor(
    vendor_id: str,
    body: VendorUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> VendorOut:
    v = await db.get(Vendor, vendor_id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "vendor not found")

    updates = body.model_dump(exclude_unset=True)
    if "category" in updates and updates["category"] not in VALID_VENDOR_CATEGORIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid category. Valid: {VALID_VENDOR_CATEGORIES}",
        )

    for k, v_val in updates.items():
        setattr(v, k, v_val)
    v.updated_at = _utcnow()

    await db.commit()
    await db.refresh(v)
    log.info("vendor.updated id=%s user=%s", v.id, user.id)
    return VendorOut.model_validate(v)


# ---------------------------------------------------------------------------
# Supply Chain summary + at-risk endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/v1/supply-chain/summary",
    response_model=SupplyChainSummary,
    summary="Portfolio supply chain summary",
)
async def supply_chain_summary(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> SupplyChainSummary:
    # Equipment counts + value
    equip_rows = (await db.execute(select(Equipment))).scalars().all()
    total_items = len(equip_rows)
    total_value = sum(
        (eq.unit_cost_usd or 0.0) * eq.quantity
        for eq in equip_rows
        if eq.unit_cost_usd is not None
    )
    at_risk_count = sum(1 for eq in equip_rows if _is_at_risk(eq))

    # Vendor counts
    vendor_count = (
        await db.execute(select(func.count()).select_from(Vendor))
    ).scalar_one()
    approved_vendor_count = (
        await db.execute(
            select(func.count()).select_from(Vendor).where(Vendor.prequalified == True)  # noqa: E712
        )
    ).scalar_one()

    return SupplyChainSummary(
        total_equipment_items=total_items,
        total_equipment_value_usd=round(total_value, 2),
        at_risk_count=at_risk_count,
        approved_vendor_count=approved_vendor_count,
        vendor_count=vendor_count,
    )


@router.get(
    "/v1/supply-chain/at-risk",
    response_model=EquipmentListResponse,
    summary="All at-risk equipment",
)
async def at_risk_equipment(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> EquipmentListResponse:
    """Return all equipment where delivery risk threatens schedule.

    At-risk conditions (computed server-side):
    1. status in (not_ordered, ordered) AND
       order_date + lead_time_weeks > today + 30 days
    2. status == in_transit AND expected_delivery < today + 7 days
    """
    rows = (await db.execute(select(Equipment))).scalars().all()
    at_risk = [_enrich(eq) for eq in rows if _is_at_risk(eq)]
    # Sort: in_transit (most urgent) first, then by expected_delivery
    at_risk.sort(key=lambda e: (
        0 if e.status == "in_transit" else 1,
        e.expected_delivery or date.max,
    ))
    return EquipmentListResponse(
        items=at_risk,
        total=len(at_risk),
        limit=len(at_risk),
        offset=0,
    )
