"""Customer Success routes — Sprint 2A

Endpoints:
  GET    /v1/customers                               — list customer accounts (type=customer only)
  GET    /v1/customers/summary                       — portfolio customer summary
  GET    /v1/customers/{account_id}                  — customer detail with health metrics
  PATCH  /v1/customers/{account_id}                  — update account (promote prospect → customer)

  POST   /v1/customers/{account_id}/tickets          — create support ticket
  GET    /v1/customers/{account_id}/tickets          — list tickets (filter: ?status=)
  PATCH  /v1/customers/{account_id}/tickets/{ticket_id} — update ticket status/notes

  POST   /v1/customers/{account_id}/notes            — add account note
  GET    /v1/customers/{account_id}/notes            — list notes (newest first)

  GET    /v1/customers/{account_id}/health           — health score + breakdown
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models_customers import (
    AccountNote,
    SupportTicket,
    VALID_TICKET_SEVERITIES,
    VALID_TICKET_STATUSES,
)
from app.models_pipeline import Account, Deal
from app.security import get_current_user

log = logging.getLogger("quill.customers")

router = APIRouter(tags=["customers"])


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Pydantic schemas (local to this module)
# ---------------------------------------------------------------------------

class CustomerOut(BaseModel):
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


class CustomerUpdate(BaseModel):
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


class TicketCreate(BaseModel):
    title: str
    description: Optional[str] = None
    severity: str = "P3"


class TicketUpdate(BaseModel):
    status: Optional[str] = None
    resolution_notes: Optional[str] = None
    severity: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    title: str
    description: Optional[str]
    severity: str
    status: str
    resolution_notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime]


class TicketListPage(BaseModel):
    items: list[TicketOut]
    total: int
    limit: int
    offset: int


class NoteCreate(BaseModel):
    text: str


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    text: str
    created_by: Optional[str]
    created_at: datetime


class NoteListPage(BaseModel):
    items: list[NoteOut]
    total: int
    limit: int
    offset: int


class HealthScoreBreakdown(BaseModel):
    ticket_score: float
    payment_score: float
    engagement_score: float
    total: float
    open_p1: int
    open_p2: int
    open_p3: int
    open_tickets_total: int


class CustomerDetailOut(CustomerOut):
    health: Optional[HealthScoreBreakdown] = None
    open_ticket_count: int = 0
    won_deal: Optional[dict] = None


class CustomerListPage(BaseModel):
    items: list[CustomerDetailOut]
    total: int
    limit: int
    offset: int


class CustomerSummaryOut(BaseModel):
    total_customers: int
    open_tickets: int
    has_critical_tickets: bool  # any open P1 or P2
    avg_health_score: Optional[float]
    at_risk_count: int  # health < 60


# ---------------------------------------------------------------------------
# Health score calculation
# ---------------------------------------------------------------------------

async def _compute_health(account_id: str, db: AsyncSession) -> HealthScoreBreakdown:
    """Compute health score breakdown for a customer account."""
    # Get open ticket counts by severity
    ticket_q = select(SupportTicket).where(
        SupportTicket.account_id == account_id,
        SupportTicket.status.in_(["open", "in_progress"]),
    )
    result = await db.execute(ticket_q)
    open_tickets = result.scalars().all()

    open_p1 = sum(1 for t in open_tickets if t.severity == "P1")
    open_p2 = sum(1 for t in open_tickets if t.severity == "P2")
    open_p3 = sum(1 for t in open_tickets if t.severity == "P3")
    total_open = len(open_tickets)

    # ticket_score: 100 if 0 open, -10 per P1, -5 per P2, -2 per P3
    ticket_score = 100.0
    if total_open == 0:
        ticket_score = 100.0
    else:
        ticket_score = max(0.0, 100.0 - (open_p1 * 10) - (open_p2 * 5) - (open_p3 * 2))

    payment_score = 100.0    # placeholder — no invoices yet
    engagement_score = 100.0  # placeholder

    total = (ticket_score + payment_score + engagement_score) / 3.0
    total = max(0.0, min(100.0, total))

    return HealthScoreBreakdown(
        ticket_score=round(ticket_score, 1),
        payment_score=round(payment_score, 1),
        engagement_score=round(engagement_score, 1),
        total=round(total, 1),
        open_p1=open_p1,
        open_p2=open_p2,
        open_p3=open_p3,
        open_tickets_total=total_open,
    )


async def _get_won_deal(account_id: str, db: AsyncSession) -> Optional[dict]:
    """Get the most recent Won deal for an account."""
    q = (
        select(Deal)
        .where(Deal.account_id == account_id, Deal.stage == "won")
        .order_by(Deal.updated_at.desc())
        .limit(1)
    )
    result = await db.execute(q)
    deal = result.scalar_one_or_none()
    if not deal:
        return None
    return {
        "id": deal.id,
        "name": deal.name,
        "stage": deal.stage,
        "campus_id": deal.campus_id,
        "value_usd": deal.value_usd,
    }


async def _require_customer(account_id: str, db: AsyncSession) -> Account:
    """Fetch an account, 404 if not found, 404 if not a customer."""
    q = select(Account).where(Account.id == account_id)
    result = await db.execute(q)
    acct = result.scalar_one_or_none()
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")
    if acct.type != "customer":
        raise HTTPException(
            status_code=404, detail="Account is not a customer. Promote it first."
        )
    return acct


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/v1/customers/summary", response_model=CustomerSummaryOut)
async def customer_summary(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Portfolio customer summary: total customers, open tickets, avg health, at-risk count."""
    # Total customers
    count_q = select(func.count()).select_from(Account).where(Account.type == "customer")
    total_customers = (await db.execute(count_q)).scalar_one()

    # Open tickets across all customers
    open_q = select(func.count()).select_from(SupportTicket).where(
        SupportTicket.status.in_(["open", "in_progress"])
    )
    open_tickets = (await db.execute(open_q)).scalar_one()

    # Critical (P1/P2) open tickets
    crit_q = select(func.count()).select_from(SupportTicket).where(
        SupportTicket.status.in_(["open", "in_progress"]),
        SupportTicket.severity.in_(["P1", "P2"]),
    )
    crit_count = (await db.execute(crit_q)).scalar_one()

    # Get all customer IDs for health computation
    acct_q = select(Account.id).where(Account.type == "customer")
    acct_ids = (await db.execute(acct_q)).scalars().all()

    health_scores: list[float] = []
    at_risk = 0
    for aid in acct_ids:
        h = await _compute_health(aid, db)
        health_scores.append(h.total)
        if h.total < 60:
            at_risk += 1

    avg_health = round(sum(health_scores) / len(health_scores), 1) if health_scores else None

    return CustomerSummaryOut(
        total_customers=total_customers,
        open_tickets=open_tickets,
        has_critical_tickets=crit_count > 0,
        avg_health_score=avg_health,
        at_risk_count=at_risk,
    )


@router.get("/v1/customers", response_model=CustomerListPage)
async def list_customers(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """List all customer accounts (type=customer only)."""
    base = select(Account).where(Account.type == "customer")
    count_q = select(func.count()).select_from(Account).where(Account.type == "customer")

    total = (await db.execute(count_q)).scalar_one()
    result = await db.execute(base.order_by(Account.name).offset(offset).limit(limit))
    accounts = result.scalars().all()

    items: list[CustomerDetailOut] = []
    for acct in accounts:
        health = await _compute_health(acct.id, db)
        won_deal = await _get_won_deal(acct.id, db)
        items.append(
            CustomerDetailOut(
                id=acct.id,
                name=acct.name,
                type=acct.type,
                industry=acct.industry,
                website=acct.website,
                hq_city=acct.hq_city,
                hq_state=acct.hq_state,
                primary_contact_name=acct.primary_contact_name,
                primary_contact_email=acct.primary_contact_email,
                primary_contact_phone=acct.primary_contact_phone,
                notes=acct.notes,
                created_at=acct.created_at,
                updated_at=acct.updated_at,
                health=health,
                open_ticket_count=health.open_tickets_total,
                won_deal=won_deal,
            )
        )

    return CustomerListPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/v1/customers/{account_id}", response_model=CustomerDetailOut)
async def get_customer(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Customer detail with health metrics."""
    acct = await _require_customer(account_id, db)
    health = await _compute_health(acct.id, db)
    won_deal = await _get_won_deal(acct.id, db)
    return CustomerDetailOut(
        id=acct.id,
        name=acct.name,
        type=acct.type,
        industry=acct.industry,
        website=acct.website,
        hq_city=acct.hq_city,
        hq_state=acct.hq_state,
        primary_contact_name=acct.primary_contact_name,
        primary_contact_email=acct.primary_contact_email,
        primary_contact_phone=acct.primary_contact_phone,
        notes=acct.notes,
        created_at=acct.created_at,
        updated_at=acct.updated_at,
        health=health,
        open_ticket_count=health.open_tickets_total,
        won_deal=won_deal,
    )


@router.patch("/v1/customers/{account_id}", response_model=CustomerOut)
async def update_customer(
    account_id: str,
    body: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Update account fields, including promoting a prospect to customer."""
    q = select(Account).where(Account.id == account_id)
    result = await db.execute(q)
    acct = result.scalar_one_or_none()
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")

    if body.type is not None and body.type not in ("prospect", "customer"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid type '{body.type}'. Must be prospect or customer.",
        )

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(acct, field, value)
    acct.updated_at = _utcnow()

    await db.commit()
    await db.refresh(acct)
    return acct


# ── Tickets ───────────────────────────────────────────────────────────────────

@router.post(
    "/v1/customers/{account_id}/tickets",
    response_model=TicketOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_ticket(
    account_id: str,
    body: TicketCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Create a support ticket for a customer account."""
    await _require_customer(account_id, db)

    if body.severity not in VALID_TICKET_SEVERITIES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid severity '{body.severity}'. Must be one of: {VALID_TICKET_SEVERITIES}",
        )

    now = _utcnow()
    ticket = SupportTicket(
        account_id=account_id,
        title=body.title,
        description=body.description,
        severity=body.severity,
        status="open",
        created_at=now,
        updated_at=now,
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    log.info("ticket.created id=%s account=%s severity=%s", ticket.id, account_id, body.severity)
    return ticket


@router.get("/v1/customers/{account_id}/tickets", response_model=TicketListPage)
async def list_tickets(
    account_id: str,
    ticket_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """List tickets for a customer account, optionally filtered by status."""
    await _require_customer(account_id, db)

    base = select(SupportTicket).where(SupportTicket.account_id == account_id)
    count_base = select(func.count()).select_from(SupportTicket).where(
        SupportTicket.account_id == account_id
    )

    if ticket_status:
        if ticket_status not in VALID_TICKET_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status '{ticket_status}'. Must be one of: {VALID_TICKET_STATUSES}",
            )
        base = base.where(SupportTicket.status == ticket_status)
        count_base = count_base.where(SupportTicket.status == ticket_status)

    total = (await db.execute(count_base)).scalar_one()
    result = await db.execute(
        base.order_by(SupportTicket.created_at.desc()).offset(offset).limit(limit)
    )
    tickets = result.scalars().all()
    return TicketListPage(items=list(tickets), total=total, limit=limit, offset=offset)


@router.patch("/v1/customers/{account_id}/tickets/{ticket_id}", response_model=TicketOut)
async def update_ticket(
    account_id: str,
    ticket_id: str,
    body: TicketUpdate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Update ticket status and/or resolution notes."""
    await _require_customer(account_id, db)

    q = select(SupportTicket).where(
        SupportTicket.id == ticket_id,
        SupportTicket.account_id == account_id,
    )
    result = await db.execute(q)
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if body.status is not None and body.status not in VALID_TICKET_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{body.status}'. Must be one of: {VALID_TICKET_STATUSES}",
        )
    if body.severity is not None and body.severity not in VALID_TICKET_SEVERITIES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid severity '{body.severity}'. Must be one of: {VALID_TICKET_SEVERITIES}",
        )

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(ticket, field, value)

    now = _utcnow()
    ticket.updated_at = now

    # Auto-set resolved_at when moving to resolved/closed
    if body.status in ("resolved", "closed") and ticket.resolved_at is None:
        ticket.resolved_at = now

    await db.commit()
    await db.refresh(ticket)
    return ticket


# ── Notes ─────────────────────────────────────────────────────────────────────

@router.post(
    "/v1/customers/{account_id}/notes",
    response_model=NoteOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_note(
    account_id: str,
    body: NoteCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Add a note to a customer account."""
    await _require_customer(account_id, db)

    note = AccountNote(
        account_id=account_id,
        text=body.text,
        created_by=getattr(user, "email", None) or getattr(user, "id", None),
        created_at=_utcnow(),
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


@router.get("/v1/customers/{account_id}/notes", response_model=NoteListPage)
async def list_notes(
    account_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """List notes for a customer account (newest first)."""
    await _require_customer(account_id, db)

    count_q = select(func.count()).select_from(AccountNote).where(
        AccountNote.account_id == account_id
    )
    total = (await db.execute(count_q)).scalar_one()

    q = (
        select(AccountNote)
        .where(AccountNote.account_id == account_id)
        .order_by(AccountNote.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(q)
    notes = result.scalars().all()
    return NoteListPage(items=list(notes), total=total, limit=limit, offset=offset)


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/v1/customers/{account_id}/health", response_model=HealthScoreBreakdown)
async def customer_health(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Health score + breakdown for a customer account."""
    await _require_customer(account_id, db)
    return await _compute_health(account_id, db)
