"""Projects routes — Sprint DC.2

Endpoints:
  POST  /v1/projects              — create a project (from site or standalone)
  GET   /v1/projects              — list projects for current user
  GET   /v1/projects/{id}         — get a single project
  PATCH /v1/projects/{id}         — advance phase or update status/notes
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models_projects import Project, VALID_PHASES, VALID_STATUSES
from app.security import get_current_user

log = logging.getLogger("quill.projects")

router = APIRouter(prefix="/v1/projects", tags=["projects"])

# ---------------------------------------------------------------------------
# Phases in order (for advancement logic)
# ---------------------------------------------------------------------------
PHASE_ORDER = [
    "site_control",
    "permitting",
    "design",
    "construction",
    "commissioning",
    "turnover",
]


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    address: Optional[str] = None
    site_id: Optional[str] = None
    site_score: Optional[float] = None
    site_verdict: Optional[str] = None
    workload_type: Optional[str] = None
    phase: str
    status: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    items: list[ProjectOut]
    total: int
    limit: int
    offset: int


class ProjectCreateIn(BaseModel):
    """Payload for POST /v1/projects"""
    name: str
    address: Optional[str] = None
    site_id: Optional[str] = None
    site_score: Optional[float] = None
    site_verdict: Optional[str] = None
    workload_type: Optional[str] = None
    phase: str = "site_control"
    status: str = "active"
    notes: Optional[str] = None


class ProjectUpdateIn(BaseModel):
    """Payload for PATCH /v1/projects/{id}"""
    phase: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    advance_phase: bool = False  # if True, auto-advance to next phase


# ---------------------------------------------------------------------------
# POST /v1/projects
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project (from site or standalone)",
)
async def create_project(
    body: ProjectCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ProjectOut:
    if body.phase not in VALID_PHASES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"phase must be one of {VALID_PHASES}",
        )
    if body.status not in VALID_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"status must be one of {VALID_STATUSES}",
        )

    project = Project(
        user_id=str(user.id),
        name=body.name,
        address=body.address,
        site_id=body.site_id,
        site_score=body.site_score,
        site_verdict=body.site_verdict,
        workload_type=body.workload_type,
        phase=body.phase,
        status=body.status,
        notes=body.notes,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    log.info(
        "project created id=%s user=%s site_id=%s",
        project.id,
        user.id,
        body.site_id,
    )
    return ProjectOut.model_validate(project)


# ---------------------------------------------------------------------------
# GET /v1/projects
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List projects for the current user",
)
async def list_projects(
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ProjectListResponse:
    base_where = [Project.user_id == str(user.id)]
    if status_filter:
        base_where.append(Project.status == status_filter)

    count_result = await db.execute(
        select(func.count()).select_from(Project).where(*base_where)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(Project)
        .where(*base_where)
        .order_by(Project.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    projects = result.scalars().all()

    return ProjectListResponse(
        items=[ProjectOut.model_validate(p) for p in projects],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /v1/projects/{project_id}
# ---------------------------------------------------------------------------

@router.get(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Get a single project",
)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ProjectOut:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    if project.user_id != str(user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your project")
    return ProjectOut.model_validate(project)


# ---------------------------------------------------------------------------
# PATCH /v1/projects/{project_id}
# ---------------------------------------------------------------------------

@router.patch(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Update a project's phase, status, or notes",
)
async def update_project(
    project_id: str,
    body: ProjectUpdateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ProjectOut:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    if project.user_id != str(user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your project")

    if body.advance_phase:
        try:
            current_idx = PHASE_ORDER.index(project.phase)
        except ValueError:
            current_idx = -1
        if current_idx < len(PHASE_ORDER) - 1:
            project.phase = PHASE_ORDER[current_idx + 1]
        else:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "project is already at the final phase (turnover)",
            )
    elif body.phase is not None:
        if body.phase not in VALID_PHASES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"phase must be one of {VALID_PHASES}",
            )
        project.phase = body.phase

    if body.status is not None:
        if body.status not in VALID_STATUSES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"status must be one of {VALID_STATUSES}",
            )
        project.status = body.status

    if body.notes is not None:
        project.notes = body.notes

    project.updated_at = _utcnow()
    await db.commit()
    await db.refresh(project)

    log.info("project updated id=%s phase=%s status=%s", project.id, project.phase, project.status)
    return ProjectOut.model_validate(project)
