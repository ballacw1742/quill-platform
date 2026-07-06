"""Facility Operations routes — Sprint 1A

Endpoints:
  POST   /v1/campuses                               — create campus
  GET    /v1/campuses                               — list all campuses
  GET    /v1/campuses/{campus_id}                   — get campus detail
  PATCH  /v1/campuses/{campus_id}                   — update campus
  POST   /v1/campuses/{campus_id}/incidents         — log incident
  GET    /v1/campuses/{campus_id}/incidents         — list incidents (newest first)
  PATCH  /v1/campuses/{campus_id}/incidents/{incident_id}  — update incident
  POST   /v1/campuses/{campus_id}/metrics           — record a metric data point
  GET    /v1/campuses/{campus_id}/metrics           — get metric history (last 30 days)
  POST   /v1/campuses/from-project/{project_id}     — promote a project to campus
  GET    /v1/campuses/deploy-templates              — template catalog (Sprint 5.4)
  POST   /v1/campuses/deploy-from-template          — 48h campus deployment workflow (Sprint 5.4)

All endpoints require Bearer auth via Depends(get_current_user).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models_compliance import ComplianceChecklist, ComplianceChecklistItem
from app.models_operations import (
    Campus,
    CampusIncident,
    CampusMetric,
    CampusMonitoringAgent,
    VALID_CAMPUS_STATUSES,
    VALID_INCIDENT_SEVERITIES,
    VALID_INCIDENT_STATUSES,
    VALID_METRIC_TYPES,
)
from app.models_projects import Project
from app.models_supply_chain import Equipment, Vendor
from app.rate_limit import GET_LIMIT, POST_LIMIT, limiter
from app.security import get_current_user, get_current_user_or_agent
from app.services.campus_template_engine import (
    TemplateResolutionError,
    catalog_summary,
    resolve_template,
)

log = logging.getLogger("quill.operations")

router = APIRouter(prefix="/v1/campuses", tags=["operations"])


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_campus(campus_id: str, db: AsyncSession) -> Campus:
    campus = await db.get(Campus, campus_id)
    if campus is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "campus not found")
    return campus


async def _active_incident_count(campus_id: str, db: AsyncSession) -> int:
    """Count open/investigating P1+P2 incidents for a campus."""
    result = await db.execute(
        select(func.count(CampusIncident.id))
        .where(
            CampusIncident.campus_id == campus_id,
            CampusIncident.severity.in_(["P1", "P2"]),
            CampusIncident.status.in_(["open", "investigating"]),
        )
    )
    return result.scalar_one() or 0


# ---------------------------------------------------------------------------
# Schemas — Campus
# ---------------------------------------------------------------------------

class CampusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: Optional[str] = None
    name: str
    address: Optional[str] = None
    mw_capacity: Optional[float] = None
    mw_live: Optional[float] = None
    status: str
    pue_target: Optional[float] = None
    pue_current: Optional[float] = None
    uptime_pct: Optional[float] = None
    power_mw_current: Optional[float] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Computed at query time — not stored
    active_p1_p2_count: int = 0


class CampusListResponse(BaseModel):
    items: list[CampusOut]
    total: int
    limit: int
    offset: int


class CampusCreateIn(BaseModel):
    name: str
    address: Optional[str] = None
    mw_capacity: Optional[float] = None
    mw_live: Optional[float] = None
    status: str = "commissioning"
    pue_target: Optional[float] = None
    notes: Optional[str] = None
    project_id: Optional[str] = None


class CampusUpdateIn(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    mw_capacity: Optional[float] = None
    mw_live: Optional[float] = None
    status: Optional[str] = None
    pue_target: Optional[float] = None
    pue_current: Optional[float] = None
    uptime_pct: Optional[float] = None
    power_mw_current: Optional[float] = None
    notes: Optional[str] = None
    project_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Schemas — Incidents
# ---------------------------------------------------------------------------

class CampusIncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    campus_id: str
    severity: str
    title: str
    description: Optional[str] = None
    status: str
    impact: Optional[str] = None
    opened_at: datetime
    resolved_at: Optional[datetime] = None
    rca_notes: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: datetime


class CampusIncidentListResponse(BaseModel):
    items: list[CampusIncidentOut]
    total: int


class CampusIncidentCreateIn(BaseModel):
    title: str
    severity: str  # P1 | P2 | P3 | P4
    description: Optional[str] = None
    impact: Optional[str] = None


class CampusIncidentUpdateIn(BaseModel):
    status: Optional[str] = None   # open | investigating | resolved | closed
    title: Optional[str] = None
    description: Optional[str] = None
    impact: Optional[str] = None
    rca_notes: Optional[str] = None
    resolved_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Schemas — Metrics
# ---------------------------------------------------------------------------

class CampusMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    campus_id: str
    metric_type: str
    value: float
    unit: Optional[str] = None
    recorded_at: datetime


class CampusMetricListResponse(BaseModel):
    items: list[CampusMetricOut]
    total: int


class CampusMetricCreateIn(BaseModel):
    metric_type: str  # pue | uptime_pct | power_mw | temp_avg | cooling_efficiency
    value: float
    unit: Optional[str] = None
    recorded_at: Optional[datetime] = None  # defaults to now


# ---------------------------------------------------------------------------
# Campus — promote from project
# ---------------------------------------------------------------------------

class PromoteFromProjectIn(BaseModel):
    name: str
    address: Optional[str] = None
    mw_capacity: Optional[float] = None
    pue_target: Optional[float] = None
    notes: Optional[str] = None


# ===========================================================================
# POST /v1/campuses
# ===========================================================================

@router.post(
    "",
    response_model=CampusOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a campus",
)
async def create_campus(
    body: CampusCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> CampusOut:
    if body.status not in VALID_CAMPUS_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"status must be one of {VALID_CAMPUS_STATUSES}",
        )
    campus = Campus(
        name=body.name,
        address=body.address,
        mw_capacity=body.mw_capacity,
        mw_live=body.mw_live,
        status=body.status,
        pue_target=body.pue_target,
        notes=body.notes,
        project_id=body.project_id,
    )
    db.add(campus)
    await db.commit()
    await db.refresh(campus)
    log.info("campus created id=%s name=%s user=%s", campus.id, campus.name, user.id)
    out = CampusOut.model_validate(campus)
    return out


# ===========================================================================
# GET /v1/campuses
# ===========================================================================

@router.get(
    "",
    response_model=CampusListResponse,
    summary="List all campuses",
)
async def list_campuses(
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = None,
    project_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_or_agent),
) -> CampusListResponse:
    base_where = []
    if status_filter:
        base_where.append(Campus.status == status_filter)
    # Sprint 5.1 — allow the project detail page to check whether a project has
    # already graduated to a campus (Project → Campus "Go Live" flow).
    if project_id:
        base_where.append(Campus.project_id == project_id)

    count_result = await db.execute(
        select(func.count()).select_from(Campus).where(*base_where)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(Campus)
        .where(*base_where)
        .order_by(Campus.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    campuses = result.scalars().all()

    items = []
    for c in campuses:
        out = CampusOut.model_validate(c)
        out.active_p1_p2_count = await _active_incident_count(c.id, db)
        items.append(out)

    return CampusListResponse(items=items, total=total, limit=limit, offset=offset)


# ===========================================================================
# Sprint 5.4 — Campus Template Automation (48-hour deployment workflow)
#
# NOTE: these routes are registered BEFORE GET /v1/campuses/{campus_id} so
# the literal paths ("deploy-templates", "deploy-from-template") are not
# captured by the {campus_id} path parameter.
# ===========================================================================

class MonitoringAgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    campus_id: str
    agent_key: str
    name: str
    agent_type: str
    status: str
    endpoint_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class MonitoringAgentListResponse(BaseModel):
    items: list[MonitoringAgentOut]
    total: int


class DeployFromTemplateIn(BaseModel):
    project_id: str
    name: str
    campus_type: str            # hyperscale | enterprise | edge (see catalog)
    jurisdiction: str           # e.g. us-oh | us-va | us-tx (falls back to default)
    region: str                 # e.g. midwest | east | south (falls back to default)
    address: Optional[str] = None
    mw_capacity: Optional[float] = None   # defaults from template if omitted
    pue_target: Optional[float] = None    # defaults from template if omitted
    notes: Optional[str] = None


class DeploymentStep(BaseModel):
    step: str                   # campus | monitoring_agents | equipment | compliance_checklist | vendors | dashboard_seed
    status: str                 # created | skipped
    count: int = 0
    ids: list[str] = []
    detail: Optional[str] = None


class DeploymentReport(BaseModel):
    campus: CampusOut
    template: dict
    steps: list[DeploymentStep]


@router.get(
    "/deploy-templates",
    summary="List available campus deployment templates (Sprint 5.4)",
)
@limiter.limit(GET_LIMIT)
async def list_deploy_templates(
    request: Request,
    user=Depends(get_current_user_or_agent),
) -> dict:
    return catalog_summary()


@router.post(
    "/deploy-from-template",
    response_model=DeploymentReport,
    status_code=status.HTTP_201_CREATED,
    summary="48-hour campus deployment — create campus + all standard artifacts from a template",
)
@limiter.limit(POST_LIMIT)
async def deploy_campus_from_template(
    request: Request,
    body: DeployFromTemplateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> DeploymentReport:
    """Single workflow that executes all six deployment steps transactionally:

      1. Campus record (linked to the Project)
      2. Monitoring agents registered for the campus
      3. Standard equipment list for the campus type
      4. Standard compliance checklist for the jurisdiction
      5. Standard vendor contact list for the region (existing vendors skipped)
      6. Operations dashboard seed metrics

    Everything is committed in ONE transaction — a failure in any step rolls
    back all previously staged artifacts.
    """
    # ── Preconditions ──────────────────────────────────────────────────
    project = await db.get(Project, body.project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")

    existing = await db.execute(
        select(Campus).where(Campus.project_id == body.project_id).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "project already has a campus — deploy-from-template is a one-time bootstrap",
        )

    try:
        tpl = resolve_template(body.campus_type, body.jurisdiction, body.region)
    except TemplateResolutionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    ct = tpl["campus"]
    steps: list[DeploymentStep] = []

    try:
        # ── Step 1: Campus record ──────────────────────────────────────
        campus = Campus(
            project_id=body.project_id,
            name=body.name,
            address=body.address or project.address,
            mw_capacity=body.mw_capacity if body.mw_capacity is not None else ct.get("default_mw_capacity"),
            mw_live=0.0,
            status="commissioning",
            pue_target=body.pue_target if body.pue_target is not None else ct.get("pue_target"),
            notes=body.notes,
        )
        db.add(campus)
        await db.flush()
        steps.append(DeploymentStep(
            step="campus", status="created", count=1, ids=[campus.id],
            detail=f"campus '{campus.name}' linked to project {body.project_id}",
        ))

        # ── Step 2: Monitoring agents ──────────────────────────────────
        agent_ids: list[str] = []
        for a in ct.get("monitoring_agents", []):
            agent = CampusMonitoringAgent(
                campus_id=campus.id,
                agent_key=a["agent_key"],
                name=a["name"],
                agent_type=a["agent_type"],
                status="registered",
            )
            db.add(agent)
            await db.flush()
            agent_ids.append(agent.id)
        steps.append(DeploymentStep(
            step="monitoring_agents",
            status="created" if agent_ids else "skipped",
            count=len(agent_ids), ids=agent_ids,
            detail=None if agent_ids else "template defines no monitoring agents",
        ))

        # ── Step 3: Standard equipment list ────────────────────────────
        equipment_ids: list[str] = []
        for e in ct.get("equipment", []):
            eq = Equipment(
                project_id=body.project_id,
                name=e["name"],
                category=e["category"],
                quantity=e.get("quantity", 1),
                unit_cost_usd=e.get("unit_cost_usd"),
                lead_time_weeks=e.get("lead_time_weeks"),
                status="not_ordered",
                notes=f"Seeded by campus template '{body.campus_type}' for campus {campus.id}",
            )
            db.add(eq)
            await db.flush()
            equipment_ids.append(eq.id)
        steps.append(DeploymentStep(
            step="equipment",
            status="created" if equipment_ids else "skipped",
            count=len(equipment_ids), ids=equipment_ids,
            detail=None if equipment_ids else "template defines no equipment",
        ))

        # ── Step 4: Compliance checklist for the jurisdiction ──────────
        comp = tpl["compliance"]
        checklist = ComplianceChecklist(
            name=comp["checklist_name"],
            framework=comp["framework"],
            campus_id=campus.id,
            status="active",
        )
        db.add(checklist)
        await db.flush()
        item_ids: list[str] = []
        for it in comp.get("items", []):
            item = ComplianceChecklistItem(
                checklist_id=checklist.id,
                control_id=it.get("control_id"),
                title=it["title"],
                description=it.get("description"),
            )
            db.add(item)
            await db.flush()
            item_ids.append(item.id)
        jur_note = (
            None if tpl["jurisdiction_used"] == tpl["jurisdiction_requested"]
            else f"jurisdiction '{tpl['jurisdiction_requested']}' not in catalog — used default"
        )
        steps.append(DeploymentStep(
            step="compliance_checklist", status="created",
            count=1 + len(item_ids), ids=[checklist.id, *item_ids],
            detail=jur_note or f"{comp['framework']} checklist with {len(item_ids)} controls",
        ))

        # ── Step 5: Vendor contact list for the region ─────────────────
        vendor_ids: list[str] = []
        skipped_vendors: list[str] = []
        for v in tpl["vendors"]:
            dup = await db.execute(select(Vendor).where(Vendor.name == v["name"]).limit(1))
            if dup.scalar_one_or_none() is not None:
                skipped_vendors.append(v["name"])
                continue
            vendor = Vendor(
                name=v["name"],
                category=v["category"],
                contact_name=v.get("contact_name"),
                contact_email=v.get("contact_email"),
                contact_phone=v.get("contact_phone"),
                prequalified=True,
                notes=f"Seeded by campus template (region '{tpl['region_used']}') for campus {campus.id}",
            )
            db.add(vendor)
            await db.flush()
            vendor_ids.append(vendor.id)
        vendor_detail_parts = []
        if tpl["region_used"] != tpl["region_requested"]:
            vendor_detail_parts.append(
                f"region '{tpl['region_requested']}' not in catalog — used default"
            )
        if skipped_vendors:
            vendor_detail_parts.append(
                f"skipped existing vendors: {', '.join(skipped_vendors)}"
            )
        steps.append(DeploymentStep(
            step="vendors",
            status="created" if vendor_ids else "skipped",
            count=len(vendor_ids), ids=vendor_ids,
            detail="; ".join(vendor_detail_parts) or None,
        ))

        # ── Step 6: Operations dashboard seed ──────────────────────────
        metric_ids: list[str] = []
        for m in ct.get("dashboard_seed", {}).get("metrics", []):
            metric = CampusMetric(
                campus_id=campus.id,
                metric_type=m["metric_type"],
                value=m["value"],
                unit=m.get("unit"),
                recorded_at=_utcnow(),
            )
            db.add(metric)
            await db.flush()
            metric_ids.append(metric.id)
            # Keep the campus summary row in sync (same behaviour as record_metric)
            if m["metric_type"] == "pue":
                campus.pue_current = m["value"]
            elif m["metric_type"] == "uptime_pct":
                campus.uptime_pct = m["value"]
            elif m["metric_type"] == "power_mw":
                campus.power_mw_current = m["value"]
        steps.append(DeploymentStep(
            step="dashboard_seed",
            status="created" if metric_ids else "skipped",
            count=len(metric_ids), ids=metric_ids,
            detail=None if metric_ids else "template defines no dashboard seed metrics",
        ))

        # ── Single transactional commit ────────────────────────────────
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 — roll back the whole deployment
        await db.rollback()
        log.error("campus_template.deploy_failed project=%s err=%s", body.project_id, exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "campus deployment failed — no artifacts were created",
        ) from exc

    await db.refresh(campus)
    log.info(
        "campus_template.deployed campus=%s project=%s type=%s jurisdiction=%s region=%s "
        "agents=%d equipment=%d checklist_items=%d vendors=%d metrics=%d user=%s",
        campus.id, body.project_id, body.campus_type,
        tpl["jurisdiction_used"], tpl["region_used"],
        len(agent_ids), len(equipment_ids), len(item_ids), len(vendor_ids), len(metric_ids),
        user.id,
    )

    return DeploymentReport(
        campus=CampusOut.model_validate(campus),
        template={
            "campus_type": tpl["campus_type"],
            "jurisdiction_requested": tpl["jurisdiction_requested"],
            "jurisdiction_used": tpl["jurisdiction_used"],
            "region_requested": tpl["region_requested"],
            "region_used": tpl["region_used"],
        },
        steps=steps,
    )


@router.get(
    "/{campus_id}/monitoring-agents",
    response_model=MonitoringAgentListResponse,
    summary="List monitoring agents registered for a campus (Sprint 5.4)",
)
async def list_monitoring_agents(
    campus_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_or_agent),
) -> MonitoringAgentListResponse:
    await _get_campus(campus_id, db)
    result = await db.execute(
        select(CampusMonitoringAgent)
        .where(CampusMonitoringAgent.campus_id == campus_id)
        .order_by(CampusMonitoringAgent.created_at.asc())
    )
    agents = result.scalars().all()
    return MonitoringAgentListResponse(
        items=[MonitoringAgentOut.model_validate(a) for a in agents],
        total=len(agents),
    )


# ===========================================================================
# GET /v1/campuses/{campus_id}
# ===========================================================================

@router.get(
    "/{campus_id}",
    response_model=CampusOut,
    summary="Get campus detail",
)
async def get_campus(
    campus_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_or_agent),
) -> CampusOut:
    campus = await _get_campus(campus_id, db)
    out = CampusOut.model_validate(campus)
    out.active_p1_p2_count = await _active_incident_count(campus_id, db)
    return out


# ===========================================================================
# PATCH /v1/campuses/{campus_id}
# ===========================================================================

@router.patch(
    "/{campus_id}",
    response_model=CampusOut,
    summary="Update campus",
)
async def update_campus(
    campus_id: str,
    body: CampusUpdateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> CampusOut:
    campus = await _get_campus(campus_id, db)

    if body.status is not None:
        if body.status not in VALID_CAMPUS_STATUSES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"status must be one of {VALID_CAMPUS_STATUSES}",
            )
        campus.status = body.status

    if body.name is not None:
        campus.name = body.name
    if body.address is not None:
        campus.address = body.address
    if body.mw_capacity is not None:
        campus.mw_capacity = body.mw_capacity
    if body.mw_live is not None:
        campus.mw_live = body.mw_live
    if body.pue_target is not None:
        campus.pue_target = body.pue_target
    if body.pue_current is not None:
        campus.pue_current = body.pue_current
    if body.uptime_pct is not None:
        campus.uptime_pct = body.uptime_pct
    if body.power_mw_current is not None:
        campus.power_mw_current = body.power_mw_current
    if body.notes is not None:
        campus.notes = body.notes
    if body.project_id is not None:
        campus.project_id = body.project_id

    campus.updated_at = _utcnow()
    await db.commit()
    await db.refresh(campus)

    out = CampusOut.model_validate(campus)
    out.active_p1_p2_count = await _active_incident_count(campus_id, db)
    log.info("campus updated id=%s status=%s", campus.id, campus.status)
    return out


# ===========================================================================
# POST /v1/campuses/from-project/{project_id}
# ===========================================================================

@router.post(
    "/from-project/{project_id}",
    response_model=CampusOut,
    status_code=status.HTTP_201_CREATED,
    summary="Promote a project to campus (go-live flow)",
)
async def promote_project_to_campus(
    project_id: str,
    body: PromoteFromProjectIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> CampusOut:
    """Create a Campus from a Project that has reached Commissioning phase."""
    campus = Campus(
        project_id=project_id,
        name=body.name,
        address=body.address,
        mw_capacity=body.mw_capacity,
        pue_target=body.pue_target,
        notes=body.notes,
        status="commissioning",
    )
    db.add(campus)
    await db.commit()
    await db.refresh(campus)
    log.info("campus promoted from project=%s campus=%s user=%s", project_id, campus.id, user.id)
    return CampusOut.model_validate(campus)


# ===========================================================================
# POST /v1/campuses/{campus_id}/incidents
# ===========================================================================

@router.post(
    "/{campus_id}/incidents",
    response_model=CampusIncidentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Log an incident at a campus",
)
async def create_incident(
    campus_id: str,
    body: CampusIncidentCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> CampusIncidentOut:
    await _get_campus(campus_id, db)

    if body.severity not in VALID_INCIDENT_SEVERITIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"severity must be one of {VALID_INCIDENT_SEVERITIES}",
        )

    incident = CampusIncident(
        campus_id=campus_id,
        severity=body.severity,
        title=body.title,
        description=body.description,
        impact=body.impact,
        status="open",
        opened_at=_utcnow(),
        created_by=str(user.id),
    )
    db.add(incident)
    await db.commit()
    await db.refresh(incident)
    log.info(
        "incident created id=%s campus=%s severity=%s user=%s",
        incident.id, campus_id, body.severity, user.id,
    )
    return CampusIncidentOut.model_validate(incident)


# ===========================================================================
# GET /v1/campuses/{campus_id}/incidents
# ===========================================================================

@router.get(
    "/{campus_id}/incidents",
    response_model=CampusIncidentListResponse,
    summary="List incidents for a campus (newest first)",
)
async def list_incidents(
    campus_id: str,
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_or_agent),
) -> CampusIncidentListResponse:
    await _get_campus(campus_id, db)

    where = [CampusIncident.campus_id == campus_id]
    if status_filter:
        where.append(CampusIncident.status == status_filter)

    result = await db.execute(
        select(CampusIncident)
        .where(*where)
        .order_by(CampusIncident.opened_at.desc())
    )
    incidents = result.scalars().all()
    return CampusIncidentListResponse(
        items=[CampusIncidentOut.model_validate(i) for i in incidents],
        total=len(incidents),
    )


# ===========================================================================
# PATCH /v1/campuses/{campus_id}/incidents/{incident_id}
# ===========================================================================

@router.patch(
    "/{campus_id}/incidents/{incident_id}",
    response_model=CampusIncidentOut,
    summary="Update an incident status or add RCA notes",
)
async def update_incident(
    campus_id: str,
    incident_id: str,
    body: CampusIncidentUpdateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> CampusIncidentOut:
    await _get_campus(campus_id, db)

    result = await db.execute(
        select(CampusIncident).where(
            CampusIncident.id == incident_id,
            CampusIncident.campus_id == campus_id,
        )
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "incident not found")

    if body.status is not None:
        if body.status not in VALID_INCIDENT_STATUSES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"status must be one of {VALID_INCIDENT_STATUSES}",
            )
        incident.status = body.status
        # Auto-set resolved_at when closing
        if body.status in ("resolved", "closed") and incident.resolved_at is None:
            incident.resolved_at = _utcnow()

    if body.title is not None:
        incident.title = body.title
    if body.description is not None:
        incident.description = body.description
    if body.impact is not None:
        incident.impact = body.impact
    if body.rca_notes is not None:
        incident.rca_notes = body.rca_notes
    if body.resolved_at is not None:
        incident.resolved_at = body.resolved_at

    incident.updated_at = _utcnow()
    await db.commit()
    await db.refresh(incident)
    log.info("incident updated id=%s status=%s", incident.id, incident.status)
    return CampusIncidentOut.model_validate(incident)


# ===========================================================================
# POST /v1/campuses/{campus_id}/metrics
# ===========================================================================

@router.post(
    "/{campus_id}/metrics",
    response_model=CampusMetricOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a metric data point",
)
async def record_metric(
    campus_id: str,
    body: CampusMetricCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> CampusMetricOut:
    await _get_campus(campus_id, db)

    if body.metric_type not in VALID_METRIC_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"metric_type must be one of {VALID_METRIC_TYPES}",
        )

    metric = CampusMetric(
        campus_id=campus_id,
        metric_type=body.metric_type,
        value=body.value,
        unit=body.unit,
        recorded_at=body.recorded_at or _utcnow(),
    )
    db.add(metric)
    await db.commit()
    await db.refresh(metric)

    # If it's a PUE or uptime reading, keep the campus row's summary current
    if body.metric_type == "pue":
        campus = await _get_campus(campus_id, db)
        campus.pue_current = body.value
        campus.updated_at = _utcnow()
        await db.commit()
    elif body.metric_type == "uptime_pct":
        campus = await _get_campus(campus_id, db)
        campus.uptime_pct = body.value
        campus.updated_at = _utcnow()
        await db.commit()
    elif body.metric_type == "power_mw":
        campus = await _get_campus(campus_id, db)
        campus.power_mw_current = body.value
        campus.updated_at = _utcnow()
        await db.commit()

    log.info("metric recorded id=%s campus=%s type=%s value=%s", metric.id, campus_id, body.metric_type, body.value)
    return CampusMetricOut.model_validate(metric)


# ===========================================================================
# GET /v1/campuses/{campus_id}/metrics
# ===========================================================================

@router.get(
    "/{campus_id}/metrics",
    response_model=CampusMetricListResponse,
    summary="Get metric history for a campus (last 30 days by default)",
)
async def list_metrics(
    campus_id: str,
    days: int = 30,
    metric_type: Optional[str] = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_or_agent),
) -> CampusMetricListResponse:
    await _get_campus(campus_id, db)

    cutoff = _utcnow() - timedelta(days=days)
    where = [
        CampusMetric.campus_id == campus_id,
        CampusMetric.recorded_at >= cutoff,
    ]
    if metric_type:
        where.append(CampusMetric.metric_type == metric_type)

    result = await db.execute(
        select(CampusMetric)
        .where(*where)
        .order_by(CampusMetric.recorded_at.desc())
        .limit(limit)
    )
    metrics = result.scalars().all()
    return CampusMetricListResponse(
        items=[CampusMetricOut.model_validate(m) for m in metrics],
        total=len(metrics),
    )
