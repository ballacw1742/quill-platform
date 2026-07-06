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

All endpoints require Bearer auth via Depends(get_current_user).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models_operations import (
    Campus,
    CampusIncident,
    CampusMetric,
    VALID_CAMPUS_STATUSES,
    VALID_INCIDENT_SEVERITIES,
    VALID_INCIDENT_STATUSES,
    VALID_METRIC_TYPES,
)
from app.security import get_current_user

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
    user=Depends(get_current_user),
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
    user=Depends(get_current_user),
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
    user=Depends(get_current_user),
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
    user=Depends(get_current_user),
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
