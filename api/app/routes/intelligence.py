"""Executive Intelligence routes — Sprint 3B

Endpoints:
  GET /v1/intelligence/kpis          — company-wide KPI snapshot
  GET /v1/intelligence/exceptions    — cross-module exceptions requiring attention
  GET /v1/intelligence/brief         — morning brief (structured text summary)
  GET /v1/intelligence/activity      — recent agent activity (last 24h)

All endpoints require Bearer auth via Depends(get_current_user).
No new DB models — reads from existing tables only.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import ApprovalItem as ApprovalItemModel
from app.models_operations import Campus, CampusIncident
from app.models_pipeline import Account, Deal
from app.models_projects import Project
from app.models_customers import SupportTicket
from app.models_supply_chain import Equipment
from app.models_requests import RequestRecord
from app.routes.supply_chain import _is_at_risk
from app.security import get_current_user

log = logging.getLogger("quill.intelligence")

router = APIRouter(prefix="/v1/intelligence", tags=["intelligence"])


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class KpiSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mw_under_site_control: float
    mw_under_construction: float
    mw_live: float
    total_arr_usd: float
    pipeline_value_usd: float
    active_incidents_p1_p2: int
    avg_pue: Optional[float]
    open_customer_tickets: int
    at_risk_equipment_count: int
    sites_in_pipeline: int
    active_projects: int
    active_customers: int
    computed_at: datetime


class ExceptionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    module: str       # OPERATIONS | SALES | SUPPLY CHAIN | FINANCE | CUSTOMERS | SITES | PROJECTS
    severity: str     # P1 | P2 | WARNING | INFO
    title: str
    description: str
    created_at: datetime
    meta: dict[str, Any] = {}


class ExceptionList(BaseModel):
    items: list[ExceptionItem]
    total: int


class BriefSection(BaseModel):
    title: str
    summary: str
    action_items: list[str] = []


class MorningBrief(BaseModel):
    generated_at: datetime
    incidents: BriefSection
    revenue: BriefSection
    construction: BriefSection
    sites: BriefSection
    customers: BriefSection
    supply_chain: BriefSection
    action_items: BriefSection


class AgentActivityItem(BaseModel):
    id: str
    agent_name: str
    intent: str
    status: str
    created_at: datetime
    updated_at: datetime
    message_preview: Optional[str] = None


class AgentActivityList(BaseModel):
    items: list[AgentActivityItem]
    total: int
    window_hours: int = 24


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_usd(v: float) -> str:
    if v >= 1_000_000_000:
        return f"${v / 1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    return f"${v:,.0f}"


def _fmt_mw(v: float) -> str:
    return f"{v:.1f} MW"


# ---------------------------------------------------------------------------
# GET /v1/intelligence/kpis
# ---------------------------------------------------------------------------

@router.get("/kpis", response_model=KpiSnapshot, summary="Company-wide KPI snapshot")
async def get_kpis(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> KpiSnapshot:
    """Compute company-wide KPIs from existing tables. No new models."""

    # MW under site control: campuses with status in commissioning|live
    # (sites are proxied from DataSite, so we use campuses as the source of truth)
    # Actually: mw_under_site_control = sum mw_capacity from campuses with
    # status not in (decommissioned, cancelled). Campuses reflect sites that
    # have been promoted to construction or live.
    # Per brief: mw_capacity from campuses with status=commissioning|live
    r = await db.execute(
        select(func.coalesce(func.sum(Campus.mw_capacity), 0)).where(
            Campus.status.in_(["commissioning", "live"])
        )
    )
    mw_under_site_control: float = float(r.scalar() or 0)

    # MW under construction: campuses with status=commissioning
    r = await db.execute(
        select(func.coalesce(func.sum(Campus.mw_capacity), 0)).where(
            Campus.status == "commissioning"
        )
    )
    mw_under_construction: float = float(r.scalar() or 0)

    # MW live: sum mw_live from campuses with status=live
    r = await db.execute(
        select(func.coalesce(func.sum(Campus.mw_live), 0)).where(
            Campus.status == "live"
        )
    )
    mw_live: float = float(r.scalar() or 0)

    # Total ARR: sum value_usd from won deals
    r = await db.execute(
        select(func.coalesce(func.sum(Deal.value_usd), 0)).where(
            Deal.stage == "won"
        )
    )
    total_arr_usd: float = float(r.scalar() or 0)

    # Pipeline value: sum value_usd from active (non-won, non-lost) deals
    r = await db.execute(
        select(func.coalesce(func.sum(Deal.value_usd), 0)).where(
            Deal.stage.notin_(["won", "lost"])
        )
    )
    pipeline_value_usd: float = float(r.scalar() or 0)

    # Active P1/P2 incidents
    r = await db.execute(
        select(func.count(CampusIncident.id)).where(
            CampusIncident.severity.in_(["P1", "P2"]),
            CampusIncident.status.in_(["open", "investigating"]),
        )
    )
    active_incidents_p1_p2: int = int(r.scalar() or 0)

    # Average PUE across live campuses
    r = await db.execute(
        select(func.avg(Campus.pue_current)).where(
            Campus.status == "live",
            Campus.pue_current.isnot(None),
        )
    )
    avg_pue_raw = r.scalar()
    avg_pue: Optional[float] = round(float(avg_pue_raw), 3) if avg_pue_raw is not None else None

    # Open customer tickets
    r = await db.execute(
        select(func.count(SupportTicket.id)).where(
            SupportTicket.status.in_(["open", "in_progress"])
        )
    )
    open_customer_tickets: int = int(r.scalar() or 0)

    # At-risk equipment: computed in Python (mirrors _is_at_risk logic)
    r = await db.execute(select(Equipment))
    all_equipment = r.scalars().all()
    at_risk_equipment_count = sum(1 for eq in all_equipment if _is_at_risk(eq))

    # Sites in pipeline: projects not in decided stage (active, planning, on_hold)
    # Since sites proxy to DataSite, we use project count as a proxy for "sites in pipeline"
    r = await db.execute(
        select(func.count(Project.id)).where(
            Project.status.in_(["planning", "active", "on_hold"])
        )
    )
    sites_in_pipeline: int = int(r.scalar() or 0)

    # Active projects
    r = await db.execute(
        select(func.count(Project.id)).where(Project.status == "active")
    )
    active_projects: int = int(r.scalar() or 0)

    # Active customers: accounts with type=customer
    r = await db.execute(
        select(func.count(Account.id)).where(Account.type == "customer")
    )
    active_customers: int = int(r.scalar() or 0)

    return KpiSnapshot(
        mw_under_site_control=mw_under_site_control,
        mw_under_construction=mw_under_construction,
        mw_live=mw_live,
        total_arr_usd=total_arr_usd,
        pipeline_value_usd=pipeline_value_usd,
        active_incidents_p1_p2=active_incidents_p1_p2,
        avg_pue=avg_pue,
        open_customer_tickets=open_customer_tickets,
        at_risk_equipment_count=at_risk_equipment_count,
        sites_in_pipeline=sites_in_pipeline,
        active_projects=active_projects,
        active_customers=active_customers,
        computed_at=_utcnow(),
    )


# ---------------------------------------------------------------------------
# GET /v1/intelligence/exceptions
# ---------------------------------------------------------------------------

@router.get("/exceptions", response_model=ExceptionList, summary="Cross-module exception feed")
async def get_exceptions(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> ExceptionList:
    """Return all cross-module exceptions requiring attention."""
    now = _utcnow()
    items: list[ExceptionItem] = []
    exc_id = 0

    def _next_id() -> str:
        nonlocal exc_id
        exc_id += 1
        return f"exc-{exc_id}"

    # 1. P1/P2 campus incidents (open or investigating)
    r = await db.execute(
        select(CampusIncident, Campus.name.label("campus_name"))
        .join(Campus, Campus.id == CampusIncident.campus_id)
        .where(
            CampusIncident.severity.in_(["P1", "P2"]),
            CampusIncident.status.in_(["open", "investigating"]),
        )
        .order_by(CampusIncident.severity, CampusIncident.opened_at)
    )
    for inc, campus_name in r.all():
        items.append(ExceptionItem(
            id=_next_id(),
            module="OPERATIONS",
            severity=inc.severity,
            title=f"[{inc.severity}] {inc.title}",
            description=f"Active {inc.severity} incident at {campus_name}: {inc.title}",
            created_at=inc.opened_at,
            meta={"incident_id": inc.id, "campus_name": campus_name, "status": inc.status},
        ))

    # 2. Customer P1 tickets open > 4 hours
    four_hours_ago = now - timedelta(hours=4)
    r = await db.execute(
        select(SupportTicket).where(
            SupportTicket.severity == "P1",
            SupportTicket.status.in_(["open", "in_progress"]),
            SupportTicket.created_at <= four_hours_ago,
        )
    )
    for ticket in r.scalars().all():
        age_hours = (now - ticket.created_at).total_seconds() / 3600
        items.append(ExceptionItem(
            id=_next_id(),
            module="CUSTOMERS",
            severity="P1",
            title=f"P1 Ticket Aged {age_hours:.0f}h: {ticket.title}",
            description=f"P1 support ticket open for {age_hours:.0f} hours without resolution",
            created_at=ticket.created_at,
            meta={"ticket_id": ticket.id, "account_id": ticket.account_id, "age_hours": round(age_hours, 1)},
        ))

    # 3. At-risk equipment
    r = await db.execute(select(Equipment))
    for eq in r.scalars().all():
        if _is_at_risk(eq):
            delivery_str = str(eq.expected_delivery) if eq.expected_delivery else "unknown"
            items.append(ExceptionItem(
                id=_next_id(),
                module="SUPPLY CHAIN",
                severity="WARNING",
                title=f"At-Risk: {eq.name}",
                description=f"Equipment '{eq.name}' (status: {eq.status}) at risk of late delivery — expected {delivery_str}",
                created_at=eq.created_at,
                meta={
                    "equipment_id": eq.id,
                    "project_id": eq.project_id,
                    "expected_delivery": delivery_str,
                    "status": eq.status,
                },
            ))

    # 4. Projects with forecast > budget
    r = await db.execute(
        select(Project).where(
            Project.budget_usd.isnot(None),
            Project.forecast_usd.isnot(None),
            Project.status == "active",
        )
    )
    for proj in r.scalars().all():
        if proj.forecast_usd and proj.budget_usd and proj.forecast_usd > proj.budget_usd:
            variance_pct = ((proj.forecast_usd - proj.budget_usd) / proj.budget_usd) * 100
            items.append(ExceptionItem(
                id=_next_id(),
                module="PROJECTS",
                severity="WARNING",
                title=f"Over Budget: {proj.name}",
                description=f"Project '{proj.name}' forecast exceeds budget by {variance_pct:.1f}%",
                created_at=proj.created_at,
                meta={
                    "project_id": proj.id,
                    "budget_usd": proj.budget_usd,
                    "forecast_usd": proj.forecast_usd,
                    "variance_pct": round(variance_pct, 1),
                },
            ))

    # 5. Invoices 60+ days overdue — no invoice model exists yet;
    #    use approval items in "pending" status older than 60 days as a proxy
    sixty_days_ago = now - timedelta(days=60)
    r = await db.execute(
        select(ApprovalItemModel).where(
            ApprovalItemModel.status == "pending",
            ApprovalItemModel.created_at <= sixty_days_ago,
        )
    )
    for item in r.scalars().all():
        age_days = (now - item.created_at).total_seconds() / 86400
        items.append(ExceptionItem(
            id=_next_id(),
            module="FINANCE",
            severity="WARNING",
            title=f"Stale Approval: {item.workflow}",
            description=f"Approval item '{item.workflow}' from {item.agent_id} has been pending {age_days:.0f} days",
            created_at=item.created_at,
            meta={"approval_id": item.id, "workflow": item.workflow, "age_days": round(age_days, 1)},
        ))

    # 6. Sites stuck in "researching" for > 7 days
    #    Sites are stored in DataSite (external). We use projects with status=planning
    #    older than 7 days as a proxy (projects are created when sites are being researched).
    seven_days_ago = now - timedelta(days=7)
    r = await db.execute(
        select(Project).where(
            Project.status == "planning",
            Project.created_at <= seven_days_ago,
        )
    )
    for proj in r.scalars().all():
        age_days = (now - proj.created_at).total_seconds() / 86400
        items.append(ExceptionItem(
            id=_next_id(),
            module="SITES",
            severity="INFO",
            title=f"Site Stalled: {proj.name}",
            description=f"Project '{proj.name}' has been in planning stage for {age_days:.0f} days",
            created_at=proj.created_at,
            meta={"project_id": proj.id, "age_days": round(age_days, 1)},
        ))

    # Sort: P1 first, then P2, then WARNING, then INFO, newest first within tier
    severity_order = {"P1": 0, "P2": 1, "WARNING": 2, "INFO": 3}
    items.sort(key=lambda x: (severity_order.get(x.severity, 9), -x.created_at.timestamp()))

    return ExceptionList(items=items, total=len(items))


# ---------------------------------------------------------------------------
# GET /v1/intelligence/brief
# ---------------------------------------------------------------------------

@router.get("/brief", response_model=MorningBrief, summary="Structured morning brief")
async def get_brief(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> MorningBrief:
    """Generate a structured morning brief from live data."""
    now = _utcnow()

    # --- Incidents ---
    r = await db.execute(
        select(func.count(CampusIncident.id)).where(
            CampusIncident.status.in_(["open", "investigating"])
        )
    )
    total_incidents = int(r.scalar() or 0)

    r = await db.execute(
        select(func.count(CampusIncident.id)).where(
            CampusIncident.severity.in_(["P1", "P2"]),
            CampusIncident.status.in_(["open", "investigating"]),
        )
    )
    p1p2_incidents = int(r.scalar() or 0)

    if p1p2_incidents == 0 and total_incidents == 0:
        incidents_summary = "All campuses are clear. No active incidents across the portfolio."
        incidents_actions: list[str] = []
    elif p1p2_incidents > 0:
        incidents_summary = (
            f"{p1p2_incidents} critical incident(s) (P1/P2) require immediate attention out of "
            f"{total_incidents} total open incidents. Review Operations for details."
        )
        incidents_actions = ["Review and update all P1/P2 incidents in Operations module."]
    else:
        incidents_summary = f"{total_incidents} non-critical incident(s) are open. No P1/P2 at this time."
        incidents_actions = []

    # --- Revenue ---
    r = await db.execute(
        select(func.coalesce(func.sum(Deal.value_usd), 0)).where(Deal.stage == "won")
    )
    arr = float(r.scalar() or 0)

    r = await db.execute(
        select(func.coalesce(func.sum(Deal.value_usd), 0)).where(
            Deal.stage.notin_(["won", "lost"])
        )
    )
    pipeline = float(r.scalar() or 0)

    r = await db.execute(select(func.count(Deal.id)).where(Deal.stage.notin_(["won", "lost"])))
    open_deals = int(r.scalar() or 0)

    revenue_summary = (
        f"Total ARR stands at {_fmt_usd(arr)}. "
        f"Active pipeline contains {open_deals} deal(s) worth {_fmt_usd(pipeline)}."
    )
    revenue_actions: list[str] = []
    if open_deals > 0:
        revenue_actions.append(f"Review {open_deals} open deal(s) in Pipeline for close-date updates.")

    # --- Construction ---
    r = await db.execute(
        select(func.count(Campus.id), func.coalesce(func.sum(Campus.mw_capacity), 0)).where(
            Campus.status == "commissioning"
        )
    )
    row = r.one()
    commissioning_count = int(row[0] or 0)
    commissioning_mw = float(row[1] or 0)

    r = await db.execute(
        select(func.count(Campus.id), func.coalesce(func.sum(Campus.mw_live), 0)).where(
            Campus.status == "live"
        )
    )
    row = r.one()
    live_count = int(row[0] or 0)
    live_mw = float(row[1] or 0)

    if commissioning_count > 0:
        construction_summary = (
            f"{commissioning_count} campus(es) under commissioning with {_fmt_mw(commissioning_mw)} in development. "
            f"{live_count} campus(es) are live delivering {_fmt_mw(live_mw)}."
        )
    else:
        construction_summary = (
            f"No campuses currently under commissioning. "
            f"{live_count} campus(es) live with {_fmt_mw(live_mw)} energized."
        )
    construction_actions: list[str] = []

    # --- Sites ---
    r = await db.execute(
        select(func.count(Project.id)).where(Project.status.in_(["planning", "active", "on_hold"]))
    )
    sites_in_pipeline = int(r.scalar() or 0)

    seven_days_ago = now - timedelta(days=7)
    r = await db.execute(
        select(func.count(Project.id)).where(
            Project.status == "planning",
            Project.created_at <= seven_days_ago,
        )
    )
    stalled_sites = int(r.scalar() or 0)

    sites_summary = f"{sites_in_pipeline} project(s) in active pipeline phases."
    sites_actions: list[str] = []
    if stalled_sites > 0:
        sites_summary += f" {stalled_sites} project(s) have been in planning for over 7 days."
        sites_actions.append(f"Review {stalled_sites} stalled project(s) in Sites module.")

    # --- Customers ---
    r = await db.execute(
        select(func.count(Account.id)).where(Account.type == "customer")
    )
    customer_count = int(r.scalar() or 0)

    r = await db.execute(
        select(func.count(SupportTicket.id)).where(
            SupportTicket.status.in_(["open", "in_progress"])
        )
    )
    open_tickets = int(r.scalar() or 0)

    four_hours_ago = now - timedelta(hours=4)
    r = await db.execute(
        select(func.count(SupportTicket.id)).where(
            SupportTicket.severity == "P1",
            SupportTicket.status.in_(["open", "in_progress"]),
            SupportTicket.created_at <= four_hours_ago,
        )
    )
    stale_p1_tickets = int(r.scalar() or 0)

    customers_summary = (
        f"{customer_count} active customer account(s). {open_tickets} support ticket(s) currently open."
    )
    customers_actions: list[str] = []
    if stale_p1_tickets > 0:
        customers_summary += f" {stale_p1_tickets} P1 ticket(s) have been open over 4 hours."
        customers_actions.append(f"Escalate {stale_p1_tickets} aged P1 ticket(s) in Customer Success.")

    # --- Supply Chain ---
    r = await db.execute(select(Equipment))
    all_equipment = r.scalars().all()
    at_risk_count = sum(1 for eq in all_equipment if _is_at_risk(eq))
    total_equipment = len(all_equipment)

    if at_risk_count > 0:
        supply_chain_summary = (
            f"{at_risk_count} of {total_equipment} tracked equipment item(s) are at risk of late delivery. "
            f"Review Supply Chain for procurement details."
        )
        sc_actions = [f"Review {at_risk_count} at-risk equipment item(s) in Supply Chain."]
    else:
        supply_chain_summary = (
            f"All {total_equipment} tracked equipment item(s) are on schedule. No procurement risks flagged."
        )
        sc_actions = []

    # --- Action items (aggregated) ---
    all_actions = incidents_actions + revenue_actions + construction_actions + sites_actions + customers_actions + sc_actions
    if not all_actions:
        action_summary = "No urgent action items. Portfolio is healthy."
    else:
        action_summary = f"{len(all_actions)} action item(s) require attention today."

    return MorningBrief(
        generated_at=now,
        incidents=BriefSection(title="Incidents", summary=incidents_summary, action_items=incidents_actions),
        revenue=BriefSection(title="Revenue", summary=revenue_summary, action_items=revenue_actions),
        construction=BriefSection(title="Construction", summary=construction_summary, action_items=construction_actions),
        sites=BriefSection(title="Sites", summary=sites_summary, action_items=sites_actions),
        customers=BriefSection(title="Customers", summary=customers_summary, action_items=customers_actions),
        supply_chain=BriefSection(title="Supply Chain", summary=supply_chain_summary, action_items=sc_actions),
        action_items=BriefSection(title="Action Items", summary=action_summary, action_items=all_actions),
    )


# ---------------------------------------------------------------------------
# GET /v1/intelligence/activity
# ---------------------------------------------------------------------------

@router.get("/activity", response_model=AgentActivityList, summary="Recent agent activity (last 24h)")
async def get_activity(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> AgentActivityList:
    """Return recent agent request activity from the last 24 hours."""
    since = _utcnow() - timedelta(hours=24)

    r = await db.execute(
        select(RequestRecord)
        .where(RequestRecord.created_at >= since)
        .order_by(RequestRecord.created_at.desc())
        .limit(100)
    )
    records = r.scalars().all()

    items = [
        AgentActivityItem(
            id=rec.id,
            agent_name=rec.intent,
            intent=rec.intent,
            status=rec.status,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
            message_preview=rec.message[:100] if rec.message else None,
        )
        for rec in records
    ]

    return AgentActivityList(items=items, total=len(items), window_hours=24)
