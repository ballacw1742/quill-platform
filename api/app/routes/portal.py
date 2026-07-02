"""Customer Portal routes — Sprint 4B.

Endpoints:
    GET  /v1/portal/me          — customer profile + linked campus/deal
    GET  /v1/portal/uptime      — campus uptime (filtered to customer's campus)
    GET  /v1/portal/tickets     — customer's own tickets only
    POST /v1/portal/tickets     — submit a new ticket
    PATCH /v1/portal/tickets/{id} — add comment to own ticket (status immutable)
    GET  /v1/portal/invoices    — customer's own invoices
    GET  /v1/portal/usage       — usage stub (until usage tracking is built)

Auth model:
    All routes require a valid JWT whose embedded ``account_id`` maps to an
    Account with type == "customer".  Issued by POST /v1/auth/portal-login.
    The JWT carries ``sub`` = account.id, ``role`` = "customer".
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models_customers import SupportTicket, VALID_TICKET_SEVERITIES
from app.models_finance import Invoice
from app.models_operations import Campus
from app.models_pipeline import Account, Deal

log = logging.getLogger("quill.portal")
_settings = get_settings()

router = APIRouter(prefix="/v1/portal", tags=["portal"])

ALGO = "HS256"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PortalMeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    account_id: str
    name: str
    email: Optional[str]
    linked_campus_id: Optional[str]
    linked_campus_name: Optional[str]
    linked_deal_id: Optional[str]


class PortalUptimeOut(BaseModel):
    campus_id: Optional[str]
    campus_name: Optional[str]
    uptime_pct: Optional[float]
    status: Optional[str]
    mw_capacity: Optional[float]
    mw_live: Optional[float]
    message: Optional[str] = None


class PortalTicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    description: Optional[str]
    severity: str
    status: str
    resolution_notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime]


class PortalTicketListOut(BaseModel):
    items: list[PortalTicketOut]
    total: int


class PortalTicketCreate(BaseModel):
    title: str
    severity: str = "P3"
    description: Optional[str] = None


class PortalTicketPatch(BaseModel):
    """Customers may only add a comment/note. Status changes are staff-only."""
    comment: str


class PortalInvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    invoice_number: Optional[str]
    amount_usd: float
    status: str
    issue_date: object  # date
    due_date: object    # date
    paid_date: Optional[object]
    notes: Optional[str]
    created_at: datetime


class PortalInvoiceListOut(BaseModel):
    items: list[PortalInvoiceOut]
    total: int


class PortalUsageOut(BaseModel):
    campus_name: Optional[str]
    contracted_mw: Optional[float]
    status: str
    message: str


# ---------------------------------------------------------------------------
# Auth dependency: require_customer
# ---------------------------------------------------------------------------

async def require_customer(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Account:
    """Validate Bearer JWT and confirm account type == customer."""
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "malformed authorization header")
    token = parts[1]
    try:
        payload = jwt.decode(token, _settings.SECRET_KEY, algorithms=[ALGO])
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {exc}") from exc

    account_id = payload.get("sub")
    role = payload.get("role")
    if not account_id or role != "customer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "customer portal access only")

    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalars().first()
    if account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "account not found")
    if account.type != "customer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account is not a customer")
    return account


# ---------------------------------------------------------------------------
# Helper: find the customer's linked deal → campus
# ---------------------------------------------------------------------------

async def _get_customer_deal(db: AsyncSession, account_id: str) -> Optional[Deal]:
    """Return the most-recent 'won' deal for this account, if any."""
    result = await db.execute(
        select(Deal)
        .where(Deal.account_id == account_id, Deal.stage == "won")
        .order_by(Deal.created_at.desc())
    )
    return result.scalars().first()


async def _get_campus(db: AsyncSession, campus_id: str) -> Optional[Campus]:
    result = await db.execute(select(Campus).where(Campus.id == campus_id))
    return result.scalars().first()


# ---------------------------------------------------------------------------
# GET /v1/portal/me
# ---------------------------------------------------------------------------

@router.get("/me", response_model=PortalMeOut)
async def portal_me(
    account: Account = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> PortalMeOut:
    deal = await _get_customer_deal(db, account.id)
    campus_name: Optional[str] = None
    if deal and deal.campus_id:
        campus = await _get_campus(db, deal.campus_id)
        if campus:
            campus_name = campus.name

    return PortalMeOut(
        account_id=account.id,
        name=account.name,
        email=account.primary_contact_email,
        linked_campus_id=deal.campus_id if deal else None,
        linked_campus_name=campus_name,
        linked_deal_id=deal.id if deal else None,
    )


# ---------------------------------------------------------------------------
# GET /v1/portal/uptime
# ---------------------------------------------------------------------------

@router.get("/uptime", response_model=PortalUptimeOut)
async def portal_uptime(
    account: Account = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> PortalUptimeOut:
    deal = await _get_customer_deal(db, account.id)
    if not deal or not deal.campus_id:
        return PortalUptimeOut(
            campus_id=None,
            campus_name=None,
            uptime_pct=None,
            status=None,
            mw_capacity=None,
            mw_live=None,
            message="Campus assignment pending",
        )

    campus = await _get_campus(db, deal.campus_id)
    if not campus:
        return PortalUptimeOut(
            campus_id=deal.campus_id,
            campus_name=None,
            uptime_pct=None,
            status=None,
            mw_capacity=None,
            mw_live=None,
            message="Campus data unavailable",
        )

    return PortalUptimeOut(
        campus_id=campus.id,
        campus_name=campus.name,
        uptime_pct=campus.uptime_pct,
        status=campus.status,
        mw_capacity=campus.mw_capacity,
        mw_live=campus.mw_live,
    )


# ---------------------------------------------------------------------------
# GET /v1/portal/tickets
# ---------------------------------------------------------------------------

@router.get("/tickets", response_model=PortalTicketListOut)
async def portal_tickets(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    account: Account = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> PortalTicketListOut:
    q = select(SupportTicket).where(SupportTicket.account_id == account.id)
    if status_filter:
        q = q.where(SupportTicket.status == status_filter)
    q = q.order_by(SupportTicket.created_at.desc())
    result = await db.execute(q)
    tickets = list(result.scalars().all())
    return PortalTicketListOut(
        items=[PortalTicketOut.model_validate(t) for t in tickets],
        total=len(tickets),
    )


# ---------------------------------------------------------------------------
# POST /v1/portal/tickets
# ---------------------------------------------------------------------------

@router.post("/tickets", response_model=PortalTicketOut, status_code=status.HTTP_201_CREATED)
async def portal_create_ticket(
    body: PortalTicketCreate,
    account: Account = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> PortalTicketOut:
    if body.severity not in VALID_TICKET_SEVERITIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"severity must be one of {VALID_TICKET_SEVERITIES}",
        )
    ticket = SupportTicket(
        account_id=account.id,
        title=body.title,
        severity=body.severity,
        description=body.description,
        status="open",
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    return PortalTicketOut.model_validate(ticket)


# ---------------------------------------------------------------------------
# PATCH /v1/portal/tickets/{ticket_id}
# ---------------------------------------------------------------------------

@router.patch("/tickets/{ticket_id}", response_model=PortalTicketOut)
async def portal_patch_ticket(
    ticket_id: str,
    body: PortalTicketPatch,
    account: Account = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> PortalTicketOut:
    result = await db.execute(
        select(SupportTicket).where(
            SupportTicket.id == ticket_id,
            SupportTicket.account_id == account.id,
        )
    )
    ticket = result.scalars().first()
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ticket not found")

    # Append comment to resolution_notes (customers cannot change status)
    existing_notes = ticket.resolution_notes or ""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    if existing_notes:
        ticket.resolution_notes = f"{existing_notes}\n\n[Customer {timestamp}]: {body.comment}"
    else:
        ticket.resolution_notes = f"[Customer {timestamp}]: {body.comment}"

    ticket.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(ticket)
    return PortalTicketOut.model_validate(ticket)


# ---------------------------------------------------------------------------
# GET /v1/portal/invoices
# ---------------------------------------------------------------------------

@router.get("/invoices", response_model=PortalInvoiceListOut)
async def portal_invoices(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    account: Account = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> PortalInvoiceListOut:
    q = select(Invoice).where(Invoice.account_id == account.id)
    if status_filter:
        # Map portal status names to DB values
        # Portal uses "unpaid" → DB "sent", "paid" → "paid", "overdue" → "overdue"
        status_map = {"unpaid": "sent", "paid": "paid", "overdue": "overdue"}
        db_status = status_map.get(status_filter.lower(), status_filter)
        q = q.where(Invoice.status == db_status)
    q = q.order_by(Invoice.issue_date.desc())
    result = await db.execute(q)
    invoices = list(result.scalars().all())
    return PortalInvoiceListOut(
        items=[PortalInvoiceOut.model_validate(i) for i in invoices],
        total=len(invoices),
    )


# ---------------------------------------------------------------------------
# GET /v1/portal/usage
# ---------------------------------------------------------------------------

@router.get("/usage", response_model=PortalUsageOut)
async def portal_usage(
    account: Account = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> PortalUsageOut:
    deal = await _get_customer_deal(db, account.id)
    campus_name: Optional[str] = None
    contracted_mw: Optional[float] = None
    campus_status: Optional[str] = None

    if deal:
        contracted_mw = deal.mw_required
        if deal.campus_id:
            campus = await _get_campus(db, deal.campus_id)
            if campus:
                campus_name = campus.name
                campus_status = campus.status

    return PortalUsageOut(
        campus_name=campus_name,
        contracted_mw=contracted_mw,
        status=campus_status or "unknown",
        message="Usage reporting coming soon. Contact your account manager for usage data.",
    )
