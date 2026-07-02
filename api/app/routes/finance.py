"""Finance routes — Sprint 3A

Division 6 — Portfolio financial visibility: ARR from won deals, capex from
equipment procurement, project budgets, and accounts receivable.

Endpoints:
  GET    /v1/finance/summary              — portfolio financial summary
  GET    /v1/finance/arr                  — ARR breakdown by customer/deal
  GET    /v1/finance/capex                — capex breakdown by project
  POST   /v1/finance/budget-lines         — add budget line item
  GET    /v1/finance/budget-lines         — list budget lines (?project_id=)
  PATCH  /v1/finance/budget-lines/{id}   — update budget line
  POST   /v1/finance/invoices             — create invoice
  GET    /v1/finance/invoices             — list invoices (?account_id=, ?status=)
  GET    /v1/finance/invoices/aging       — AR aging summary
  PATCH  /v1/finance/invoices/{id}        — update invoice status
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models_finance import BudgetLine, Invoice, VALID_BUDGET_CATEGORIES, VALID_INVOICE_STATUSES
from app.models_pipeline import Account, Deal
from app.models_projects import Project
from app.models_supply_chain import Equipment
from app.security import get_current_user

log = logging.getLogger("quill.finance")

router = APIRouter(tags=["finance"])


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return datetime.now(UTC).date()


# ---------------------------------------------------------------------------
# Pydantic schemas (inline — follows supply_chain.py pattern)
# ---------------------------------------------------------------------------

class FinanceSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_arr_usd: float
    total_pipeline_value_usd: float
    total_capex_committed_usd: float
    total_project_budget_usd: float
    total_project_forecast_usd: float
    budget_variance_usd: float
    total_outstanding_invoices_usd: float
    overdue_invoices_count: int


class ArrLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    deal_id: str
    deal_name: str
    account_id: str
    account_name: str
    value_usd: Optional[float]
    mw_required: Optional[float]
    campus_id: Optional[str]


class ArrResponse(BaseModel):
    items: list[ArrLineOut]
    total: int


class CapexLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: str
    project_name: str
    budget_usd: Optional[float]
    committed_usd: Optional[float]
    forecast_usd: Optional[float]
    equipment_total_usd: float


class CapexResponse(BaseModel):
    items: list[CapexLineOut]
    total: int


class BudgetLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: Optional[str]
    category: str
    description: str
    budget_usd: float
    committed_usd: float
    actual_usd: float
    period: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class BudgetLineListOut(BaseModel):
    items: list[BudgetLineOut]
    total: int
    limit: int
    offset: int


class BudgetLineCreate(BaseModel):
    project_id: Optional[str] = None
    category: str
    description: str
    budget_usd: float = 0.0
    committed_usd: float = 0.0
    actual_usd: float = 0.0
    period: Optional[str] = None
    notes: Optional[str] = None


class BudgetLinePatch(BaseModel):
    project_id: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    budget_usd: Optional[float] = None
    committed_usd: Optional[float] = None
    actual_usd: Optional[float] = None
    period: Optional[str] = None
    notes: Optional[str] = None


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: Optional[str]
    deal_id: Optional[str]
    invoice_number: Optional[str]
    amount_usd: float
    status: str
    issue_date: date
    due_date: date
    paid_date: Optional[date]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class InvoiceListOut(BaseModel):
    items: list[InvoiceOut]
    total: int
    limit: int
    offset: int


class InvoiceCreate(BaseModel):
    account_id: Optional[str] = None
    deal_id: Optional[str] = None
    invoice_number: Optional[str] = None
    amount_usd: float
    status: str = "draft"
    issue_date: date
    due_date: date
    paid_date: Optional[date] = None
    notes: Optional[str] = None


class InvoicePatch(BaseModel):
    account_id: Optional[str] = None
    deal_id: Optional[str] = None
    invoice_number: Optional[str] = None
    amount_usd: Optional[float] = None
    status: Optional[str] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    paid_date: Optional[date] = None
    notes: Optional[str] = None


class AgingBucket(BaseModel):
    label: str
    count: int
    total_usd: float


class ArAgingOut(BaseModel):
    buckets: list[AgingBucket]
    total_outstanding_usd: float
    overdue_invoices_count: int


# ---------------------------------------------------------------------------
# GET /v1/finance/summary
# ---------------------------------------------------------------------------

@router.get("/v1/finance/summary", response_model=FinanceSummaryOut)
async def get_finance_summary(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> FinanceSummaryOut:
    """Portfolio financial summary: ARR, pipeline, capex, project budgets, AR."""
    today = _today()

    # Total ARR: won deals
    arr_result = await db.execute(
        select(func.coalesce(func.sum(Deal.value_usd), 0.0)).where(Deal.stage == "won")
    )
    total_arr = float(arr_result.scalar_one())

    # Pipeline value: active deals (not won/lost)
    pipeline_result = await db.execute(
        select(func.coalesce(func.sum(Deal.value_usd), 0.0)).where(
            Deal.stage.notin_(["won", "lost"])
        )
    )
    total_pipeline = float(pipeline_result.scalar_one())

    # Capex committed: sum(unit_cost_usd * quantity) across all equipment
    capex_result = await db.execute(
        select(func.coalesce(func.sum(Equipment.unit_cost_usd * Equipment.quantity), 0.0)).where(
            Equipment.unit_cost_usd.isnot(None)
        )
    )
    total_capex = float(capex_result.scalar_one())

    # Project budgets and forecasts
    budget_result = await db.execute(
        select(
            func.coalesce(func.sum(Project.budget_usd), 0.0),
            func.coalesce(func.sum(Project.forecast_usd), 0.0),
        )
    )
    budget_row = budget_result.one()
    total_project_budget = float(budget_row[0])
    total_project_forecast = float(budget_row[1])
    budget_variance = total_project_forecast - total_project_budget

    # Outstanding invoices (not paid, not cancelled)
    outstanding_result = await db.execute(
        select(func.coalesce(func.sum(Invoice.amount_usd), 0.0)).where(
            Invoice.status.notin_(["paid", "cancelled"])
        )
    )
    total_outstanding = float(outstanding_result.scalar_one())

    # Overdue invoices: past due_date and status != paid
    overdue_result = await db.execute(
        select(func.count(Invoice.id)).where(
            Invoice.due_date < today,
            Invoice.status.notin_(["paid", "cancelled"]),
        )
    )
    overdue_count = int(overdue_result.scalar_one())

    return FinanceSummaryOut(
        total_arr_usd=total_arr,
        total_pipeline_value_usd=total_pipeline,
        total_capex_committed_usd=total_capex,
        total_project_budget_usd=total_project_budget,
        total_project_forecast_usd=total_project_forecast,
        budget_variance_usd=budget_variance,
        total_outstanding_invoices_usd=total_outstanding,
        overdue_invoices_count=overdue_count,
    )


# ---------------------------------------------------------------------------
# GET /v1/finance/arr
# ---------------------------------------------------------------------------

@router.get("/v1/finance/arr", response_model=ArrResponse)
async def get_arr_breakdown(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> ArrResponse:
    """ARR breakdown: all Won deals with account name, MW, and value."""
    result = await db.execute(
        select(Deal, Account.name.label("account_name"))
        .join(Account, Deal.account_id == Account.id)
        .where(Deal.stage == "won")
        .order_by(Deal.value_usd.desc().nulls_last())
    )
    rows = result.all()

    items = [
        ArrLineOut(
            deal_id=deal.id,
            deal_name=deal.name,
            account_id=deal.account_id,
            account_name=account_name,
            value_usd=deal.value_usd,
            mw_required=deal.mw_required,
            campus_id=deal.campus_id,
        )
        for deal, account_name in rows
    ]

    return ArrResponse(items=items, total=len(items))


# ---------------------------------------------------------------------------
# GET /v1/finance/capex
# ---------------------------------------------------------------------------

@router.get("/v1/finance/capex", response_model=CapexResponse)
async def get_capex_breakdown(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> CapexResponse:
    """CapEx breakdown: all projects with budget vs forecast and equipment totals."""
    # Fetch all projects
    projects_result = await db.execute(
        select(Project).order_by(Project.created_at.desc())
    )
    projects = projects_result.scalars().all()

    items = []
    for proj in projects:
        # Equipment total for this project
        eq_result = await db.execute(
            select(func.coalesce(func.sum(Equipment.unit_cost_usd * Equipment.quantity), 0.0)).where(
                Equipment.project_id == proj.id,
                Equipment.unit_cost_usd.isnot(None),
            )
        )
        equipment_total = float(eq_result.scalar_one())

        items.append(
            CapexLineOut(
                project_id=proj.id,
                project_name=proj.name,
                budget_usd=proj.budget_usd,
                committed_usd=proj.committed_usd,
                forecast_usd=proj.forecast_usd,
                equipment_total_usd=equipment_total,
            )
        )

    return CapexResponse(items=items, total=len(items))


# ---------------------------------------------------------------------------
# POST /v1/finance/budget-lines
# ---------------------------------------------------------------------------

@router.post("/v1/finance/budget-lines", response_model=BudgetLineOut, status_code=status.HTTP_201_CREATED)
async def create_budget_line(
    body: BudgetLineCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> BudgetLineOut:
    """Add a budget line item to a project."""
    if body.category not in VALID_BUDGET_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"category must be one of: {', '.join(VALID_BUDGET_CATEGORIES)}",
        )

    now = _utcnow()
    line = BudgetLine(
        project_id=body.project_id,
        category=body.category,
        description=body.description,
        budget_usd=body.budget_usd,
        committed_usd=body.committed_usd,
        actual_usd=body.actual_usd,
        period=body.period,
        notes=body.notes,
        created_at=now,
        updated_at=now,
    )
    db.add(line)
    await db.commit()
    await db.refresh(line)
    log.info("budget_line.created id=%s project=%s", line.id, line.project_id)
    return BudgetLineOut.model_validate(line)


# ---------------------------------------------------------------------------
# GET /v1/finance/budget-lines
# ---------------------------------------------------------------------------

@router.get("/v1/finance/budget-lines", response_model=BudgetLineListOut)
async def list_budget_lines(
    project_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> BudgetLineListOut:
    """List budget lines, optionally filtered by project_id."""
    q = select(BudgetLine)
    if project_id:
        q = q.where(BudgetLine.project_id == project_id)

    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = int(count_result.scalar_one())

    result = await db.execute(
        q.order_by(BudgetLine.created_at.desc()).limit(limit).offset(offset)
    )
    lines = result.scalars().all()

    return BudgetLineListOut(
        items=[BudgetLineOut.model_validate(ln) for ln in lines],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# PATCH /v1/finance/budget-lines/{id}
# ---------------------------------------------------------------------------

@router.patch("/v1/finance/budget-lines/{budget_line_id}", response_model=BudgetLineOut)
async def update_budget_line(
    budget_line_id: str,
    body: BudgetLinePatch,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> BudgetLineOut:
    """Update a budget line item."""
    result = await db.execute(select(BudgetLine).where(BudgetLine.id == budget_line_id))
    line = result.scalar_one_or_none()
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget line not found")

    update_data = body.model_dump(exclude_unset=True)
    if "category" in update_data and update_data["category"] not in VALID_BUDGET_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"category must be one of: {', '.join(VALID_BUDGET_CATEGORIES)}",
        )

    for field, value in update_data.items():
        setattr(line, field, value)
    line.updated_at = _utcnow()

    await db.commit()
    await db.refresh(line)
    log.info("budget_line.updated id=%s", line.id)
    return BudgetLineOut.model_validate(line)


# ---------------------------------------------------------------------------
# POST /v1/finance/invoices
# ---------------------------------------------------------------------------

@router.post("/v1/finance/invoices", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    body: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> InvoiceOut:
    """Create a new invoice."""
    if body.status not in VALID_INVOICE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of: {', '.join(VALID_INVOICE_STATUSES)}",
        )

    now = _utcnow()
    invoice = Invoice(
        account_id=body.account_id,
        deal_id=body.deal_id,
        invoice_number=body.invoice_number,
        amount_usd=body.amount_usd,
        status=body.status,
        issue_date=body.issue_date,
        due_date=body.due_date,
        paid_date=body.paid_date,
        notes=body.notes,
        created_at=now,
        updated_at=now,
    )
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    log.info("invoice.created id=%s account=%s amount=%.2f", invoice.id, invoice.account_id, invoice.amount_usd)
    return InvoiceOut.model_validate(invoice)


# ---------------------------------------------------------------------------
# GET /v1/finance/invoices/aging  (must be before /{id} to avoid conflict)
# ---------------------------------------------------------------------------

@router.get("/v1/finance/invoices/aging", response_model=ArAgingOut)
async def get_ar_aging(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> ArAgingOut:
    """AR aging summary: invoice counts and amounts by overdue bucket."""
    today = _today()

    # Fetch all non-paid, non-cancelled invoices
    result = await db.execute(
        select(Invoice).where(Invoice.status.notin_(["paid", "cancelled"]))
    )
    invoices = result.scalars().all()

    # Bucket definitions: (label, min_days_overdue_inclusive, max_days_overdue_exclusive)
    buckets: list[dict] = [
        {"label": "Current", "count": 0, "total_usd": 0.0},
        {"label": "1–30 days", "count": 0, "total_usd": 0.0},
        {"label": "31–60 days", "count": 0, "total_usd": 0.0},
        {"label": "61–90 days", "count": 0, "total_usd": 0.0},
        {"label": "90+ days", "count": 0, "total_usd": 0.0},
    ]

    total_outstanding = 0.0
    overdue_count = 0

    for inv in invoices:
        days_overdue = (today - inv.due_date).days
        total_outstanding += inv.amount_usd

        if days_overdue <= 0:
            # Not yet due — current
            buckets[0]["count"] += 1
            buckets[0]["total_usd"] += inv.amount_usd
        elif days_overdue <= 30:
            buckets[1]["count"] += 1
            buckets[1]["total_usd"] += inv.amount_usd
            overdue_count += 1
        elif days_overdue <= 60:
            buckets[2]["count"] += 1
            buckets[2]["total_usd"] += inv.amount_usd
            overdue_count += 1
        elif days_overdue <= 90:
            buckets[3]["count"] += 1
            buckets[3]["total_usd"] += inv.amount_usd
            overdue_count += 1
        else:
            buckets[4]["count"] += 1
            buckets[4]["total_usd"] += inv.amount_usd
            overdue_count += 1

    return ArAgingOut(
        buckets=[AgingBucket(**b) for b in buckets],
        total_outstanding_usd=total_outstanding,
        overdue_invoices_count=overdue_count,
    )


# ---------------------------------------------------------------------------
# GET /v1/finance/invoices
# ---------------------------------------------------------------------------

@router.get("/v1/finance/invoices", response_model=InvoiceListOut)
async def list_invoices(
    account_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> InvoiceListOut:
    """List invoices, optionally filtered by account_id and/or status."""
    q = select(Invoice)
    if account_id:
        q = q.where(Invoice.account_id == account_id)
    if status_filter:
        if status_filter not in VALID_INVOICE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"status must be one of: {', '.join(VALID_INVOICE_STATUSES)}",
            )
        q = q.where(Invoice.status == status_filter)

    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = int(count_result.scalar_one())

    result = await db.execute(
        q.order_by(Invoice.due_date.asc()).limit(limit).offset(offset)
    )
    invoices = result.scalars().all()

    return InvoiceListOut(
        items=[InvoiceOut.model_validate(inv) for inv in invoices],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# PATCH /v1/finance/invoices/{id}
# ---------------------------------------------------------------------------

@router.patch("/v1/finance/invoices/{invoice_id}", response_model=InvoiceOut)
async def update_invoice(
    invoice_id: str,
    body: InvoicePatch,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> InvoiceOut:
    """Update an invoice (status, paid_date, etc.)."""
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    update_data = body.model_dump(exclude_unset=True)
    if "status" in update_data and update_data["status"] not in VALID_INVOICE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of: {', '.join(VALID_INVOICE_STATUSES)}",
        )

    for field, value in update_data.items():
        setattr(invoice, field, value)
    invoice.updated_at = _utcnow()

    await db.commit()
    await db.refresh(invoice)
    log.info("invoice.updated id=%s status=%s", invoice.id, invoice.status)
    return InvoiceOut.model_validate(invoice)
