"""Projects routes — Sprint DC.2 + 0.2 hardening

Endpoints:
  POST  /v1/projects              — create a project (from site or standalone)
  GET   /v1/projects              — list projects for current user
  GET   /v1/projects/{id}         — get a single project
  PATCH /v1/projects/{id}         — advance phase or update status/notes/budget

  Milestones:
  POST   /v1/projects/{id}/milestones          — create milestone
  GET    /v1/projects/{id}/milestones          — list milestones
  PATCH  /v1/projects/{id}/milestones/{mid}    — update milestone
  DELETE /v1/projects/{id}/milestones/{mid}    — delete milestone

  Construction Log:
  POST  /v1/projects/{id}/log     — add log entry
  GET   /v1/projects/{id}/log     — list log entries (newest first)

  Document links:
  POST  /v1/projects/{id}/documents  — link a document
  GET   /v1/projects/{id}/documents  — list linked documents

  Contract + Estimate links:
  POST  /v1/projects/{id}/contracts   — link contract_id
  GET   /v1/projects/{id}/contracts   — list linked contracts
  POST  /v1/projects/{id}/estimates   — link estimate_id
  GET   /v1/projects/{id}/estimates   — list linked estimates
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models_projects import (
    Project,
    ProjectContractLink,
    ProjectDocumentLink,
    ProjectEstimateLink,
    ProjectLogEntry,
    ProjectMilestone,
    VALID_ENTRY_TYPES,
    VALID_PHASES,
    VALID_STATUSES,
)
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
# Helpers
# ---------------------------------------------------------------------------

# Shared workspace: owner/partner users collaborate in one shared data space —
# they all see the same projects/requests regardless of which member created
# them. The user_id column is retained as an authorship/audit stamp. Observers
# (and any future non-member roles) remain scoped to their own records.
_WORKSPACE_ROLES = {"owner", "partner"}


def _is_workspace_member(user) -> bool:
    return getattr(user, "role", None) in _WORKSPACE_ROLES


async def _get_owned_project(project_id: str, user, db: AsyncSession) -> Project:
    """Fetch a project, enforce access, raise 404/403 as appropriate.

    Workspace members (owner/partner) share all projects; other roles are
    limited to projects they created.
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    if not _is_workspace_member(user) and project.user_id != str(user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your project")
    return project


async def _milestone_stats(project_ids: list[str], db: AsyncSession) -> dict[str, dict]:
    """Efficiently fetch milestone totals/complete/overdue for a list of project IDs."""
    if not project_ids:
        return {}
    today = datetime.now(UTC).date()
    result = await db.execute(
        select(
            ProjectMilestone.project_id,
            func.count(ProjectMilestone.id).label("total"),
            func.sum(
                case((ProjectMilestone.completed_at.is_not(None), 1), else_=0)
            ).label("complete"),
            func.sum(
                case(
                    (
                        (ProjectMilestone.completed_at.is_(None))
                        & (ProjectMilestone.due_date.is_not(None))
                        & (ProjectMilestone.due_date < today),
                        1,
                    ),
                    else_=0,
                )
            ).label("overdue"),
        )
        .where(ProjectMilestone.project_id.in_(project_ids))
        .group_by(ProjectMilestone.project_id)
    )
    return {
        row.project_id: {
            "total": int(row.total or 0),
            "complete": int(row.complete or 0),
            "overdue": int(row.overdue or 0),
        }
        for row in result
    }


def _project_out(project: Project, stats: dict | None = None) -> ProjectOut:
    """Convert a Project ORM row to ProjectOut, merging in milestone stats."""
    out = ProjectOut.model_validate(project)
    if stats:
        out.milestone_total = stats.get("total", 0)
        out.milestone_complete = stats.get("complete", 0)
        out.milestone_overdue = stats.get("overdue", 0)
    return out


# ---------------------------------------------------------------------------
# Schemas — Project
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
    budget_usd: Optional[float] = None
    committed_usd: Optional[float] = None
    forecast_usd: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    # Sprint 0.2 — computed milestone summary (set by list/detail endpoints)
    milestone_total: int = 0
    milestone_complete: int = 0
    milestone_overdue: int = 0


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
    # Sprint 0.2 — budget fields
    budget_usd: Optional[float] = None
    committed_usd: Optional[float] = None
    forecast_usd: Optional[float] = None


# ---------------------------------------------------------------------------
# Schemas — Milestones
# ---------------------------------------------------------------------------

class MilestoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    description: Optional[str] = None
    due_date: Optional[date] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


class MilestoneListResponse(BaseModel):
    items: list[MilestoneOut]
    total: int


class MilestoneCreateIn(BaseModel):
    name: str
    description: Optional[str] = None
    due_date: Optional[date] = None


class MilestoneUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[date] = None
    completed: Optional[bool] = None  # True → set completed_at; False → clear it


# ---------------------------------------------------------------------------
# Schemas — Construction Log
# ---------------------------------------------------------------------------

class LogEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    user_id: Optional[str] = None
    entry_type: str
    text: str
    created_at: datetime


class LogListResponse(BaseModel):
    items: list[LogEntryOut]
    total: int


class LogEntryCreateIn(BaseModel):
    text: str
    entry_type: str = "general"  # general | issue | milestone | decision


# ---------------------------------------------------------------------------
# Schemas — Document links
# ---------------------------------------------------------------------------

class DocumentLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    document_id: Optional[str] = None
    name: str
    url: Optional[str] = None
    created_at: datetime


class DocumentLinkListResponse(BaseModel):
    items: list[DocumentLinkOut]
    total: int


class DocumentLinkCreateIn(BaseModel):
    name: str
    document_id: Optional[str] = None
    url: Optional[str] = None


# ---------------------------------------------------------------------------
# Schemas — Contract + Estimate links
# ---------------------------------------------------------------------------

class ContractLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    contract_id: str
    created_at: datetime


class ContractLinkListResponse(BaseModel):
    items: list[ContractLinkOut]
    total: int


class ContractLinkCreateIn(BaseModel):
    contract_id: str


class EstimateLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    estimate_id: str
    created_at: datetime


class EstimateLinkListResponse(BaseModel):
    items: list[EstimateLinkOut]
    total: int


class EstimateLinkCreateIn(BaseModel):
    estimate_id: str


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
    # Workspace members see all projects (shared workspace); other roles see
    # only their own.
    base_where = []
    if not _is_workspace_member(user):
        base_where.append(Project.user_id == str(user.id))
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

    # Fetch milestone stats for all projects in one query
    all_ids = [p.id for p in projects]
    stats_by_id = await _milestone_stats(all_ids, db)

    return ProjectListResponse(
        items=[_project_out(p, stats_by_id.get(p.id)) for p in projects],
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
    project = await _get_owned_project(project_id, user, db)
    stats = await _milestone_stats([project_id], db)
    return _project_out(project, stats.get(project_id))


# ---------------------------------------------------------------------------
# PATCH /v1/projects/{project_id}
# ---------------------------------------------------------------------------

@router.patch(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Update a project's phase, status, notes, or budget",
)
async def update_project(
    project_id: str,
    body: ProjectUpdateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ProjectOut:
    project = await _get_owned_project(project_id, user, db)

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

    # Sprint 0.2 — budget fields (None means "don't touch", 0.0 is a valid value)
    if body.budget_usd is not None:
        project.budget_usd = body.budget_usd
    if body.committed_usd is not None:
        project.committed_usd = body.committed_usd
    if body.forecast_usd is not None:
        project.forecast_usd = body.forecast_usd

    project.updated_at = _utcnow()
    await db.commit()
    await db.refresh(project)

    log.info("project updated id=%s phase=%s status=%s", project.id, project.phase, project.status)
    stats = await _milestone_stats([project_id], db)
    return _project_out(project, stats.get(project_id))


# ===========================================================================
# Milestones
# ===========================================================================

@router.post(
    "/{project_id}/milestones",
    response_model=MilestoneOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a milestone for a project",
)
async def create_milestone(
    project_id: str,
    body: MilestoneCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MilestoneOut:
    await _get_owned_project(project_id, user, db)

    milestone = ProjectMilestone(
        project_id=project_id,
        name=body.name,
        description=body.description,
        due_date=body.due_date,
    )
    db.add(milestone)
    await db.commit()
    await db.refresh(milestone)
    log.info("milestone created id=%s project=%s", milestone.id, project_id)
    return MilestoneOut.model_validate(milestone)


@router.get(
    "/{project_id}/milestones",
    response_model=MilestoneListResponse,
    summary="List milestones for a project",
)
async def list_milestones(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MilestoneListResponse:
    await _get_owned_project(project_id, user, db)

    result = await db.execute(
        select(ProjectMilestone)
        .where(ProjectMilestone.project_id == project_id)
        .order_by(ProjectMilestone.due_date.asc().nulls_last(), ProjectMilestone.created_at.asc())
    )
    milestones = result.scalars().all()
    return MilestoneListResponse(
        items=[MilestoneOut.model_validate(m) for m in milestones],
        total=len(milestones),
    )


@router.patch(
    "/{project_id}/milestones/{milestone_id}",
    response_model=MilestoneOut,
    summary="Update a milestone (mark complete, change date, rename)",
)
async def update_milestone(
    project_id: str,
    milestone_id: str,
    body: MilestoneUpdateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MilestoneOut:
    await _get_owned_project(project_id, user, db)

    result = await db.execute(
        select(ProjectMilestone).where(
            ProjectMilestone.id == milestone_id,
            ProjectMilestone.project_id == project_id,
        )
    )
    milestone = result.scalar_one_or_none()
    if milestone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "milestone not found")

    if body.name is not None:
        milestone.name = body.name
    if body.description is not None:
        milestone.description = body.description
    if body.due_date is not None:
        milestone.due_date = body.due_date
    if body.completed is True and milestone.completed_at is None:
        milestone.completed_at = _utcnow()
    elif body.completed is False:
        milestone.completed_at = None

    await db.commit()
    await db.refresh(milestone)
    return MilestoneOut.model_validate(milestone)


@router.delete(
    "/{project_id}/milestones/{milestone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a milestone",
)
async def delete_milestone(
    project_id: str,
    milestone_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> None:
    await _get_owned_project(project_id, user, db)

    result = await db.execute(
        select(ProjectMilestone).where(
            ProjectMilestone.id == milestone_id,
            ProjectMilestone.project_id == project_id,
        )
    )
    milestone = result.scalar_one_or_none()
    if milestone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "milestone not found")

    await db.delete(milestone)
    await db.commit()


# ===========================================================================
# Construction Log
# ===========================================================================

@router.post(
    "/{project_id}/log",
    response_model=LogEntryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a log entry to a project",
)
async def add_log_entry(
    project_id: str,
    body: LogEntryCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> LogEntryOut:
    await _get_owned_project(project_id, user, db)

    if body.entry_type not in VALID_ENTRY_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"entry_type must be one of {VALID_ENTRY_TYPES}",
        )

    entry = ProjectLogEntry(
        project_id=project_id,
        user_id=str(user.id),
        entry_type=body.entry_type,
        text=body.text,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    log.info("log entry created id=%s project=%s type=%s", entry.id, project_id, body.entry_type)
    return LogEntryOut.model_validate(entry)


@router.get(
    "/{project_id}/log",
    response_model=LogListResponse,
    summary="Get log entries for a project (newest first)",
)
async def list_log_entries(
    project_id: str,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> LogListResponse:
    await _get_owned_project(project_id, user, db)

    result = await db.execute(
        select(ProjectLogEntry)
        .where(ProjectLogEntry.project_id == project_id)
        .order_by(ProjectLogEntry.created_at.desc())
        .limit(limit)
    )
    entries = result.scalars().all()
    return LogListResponse(
        items=[LogEntryOut.model_validate(e) for e in entries],
        total=len(entries),
    )


# ===========================================================================
# Document links
# ===========================================================================

@router.post(
    "/{project_id}/documents",
    response_model=DocumentLinkOut,
    status_code=status.HTTP_201_CREATED,
    summary="Link a document to a project",
)
async def link_document(
    project_id: str,
    body: DocumentLinkCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> DocumentLinkOut:
    await _get_owned_project(project_id, user, db)

    link = ProjectDocumentLink(
        project_id=project_id,
        document_id=body.document_id,
        name=body.name,
        url=body.url,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return DocumentLinkOut.model_validate(link)


@router.get(
    "/{project_id}/documents",
    response_model=DocumentLinkListResponse,
    summary="List documents linked to a project",
)
async def list_document_links(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> DocumentLinkListResponse:
    await _get_owned_project(project_id, user, db)

    result = await db.execute(
        select(ProjectDocumentLink)
        .where(ProjectDocumentLink.project_id == project_id)
        .order_by(ProjectDocumentLink.created_at.asc())
    )
    links = result.scalars().all()
    return DocumentLinkListResponse(
        items=[DocumentLinkOut.model_validate(lk) for lk in links],
        total=len(links),
    )


# ===========================================================================
# Contract links
# ===========================================================================

@router.post(
    "/{project_id}/contracts",
    response_model=ContractLinkOut,
    status_code=status.HTTP_201_CREATED,
    summary="Link a contract to a project",
)
async def link_contract(
    project_id: str,
    body: ContractLinkCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ContractLinkOut:
    await _get_owned_project(project_id, user, db)

    link = ProjectContractLink(
        project_id=project_id,
        contract_id=body.contract_id,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    log.info("contract linked project=%s contract=%s", project_id, body.contract_id)
    return ContractLinkOut.model_validate(link)


@router.get(
    "/{project_id}/contracts",
    response_model=ContractLinkListResponse,
    summary="List contracts linked to a project",
)
async def list_contract_links(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ContractLinkListResponse:
    await _get_owned_project(project_id, user, db)

    result = await db.execute(
        select(ProjectContractLink)
        .where(ProjectContractLink.project_id == project_id)
        .order_by(ProjectContractLink.created_at.asc())
    )
    links = result.scalars().all()
    return ContractLinkListResponse(
        items=[ContractLinkOut.model_validate(lk) for lk in links],
        total=len(links),
    )


# ===========================================================================
# Estimate links
# ===========================================================================

@router.post(
    "/{project_id}/estimates",
    response_model=EstimateLinkOut,
    status_code=status.HTTP_201_CREATED,
    summary="Link an estimate to a project",
)
async def link_estimate(
    project_id: str,
    body: EstimateLinkCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> EstimateLinkOut:
    await _get_owned_project(project_id, user, db)

    link = ProjectEstimateLink(
        project_id=project_id,
        estimate_id=body.estimate_id,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    log.info("estimate linked project=%s estimate=%s", project_id, body.estimate_id)
    return EstimateLinkOut.model_validate(link)


@router.get(
    "/{project_id}/estimates",
    response_model=EstimateLinkListResponse,
    summary="List estimates linked to a project",
)
async def list_estimate_links(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> EstimateLinkListResponse:
    await _get_owned_project(project_id, user, db)

    result = await db.execute(
        select(ProjectEstimateLink)
        .where(ProjectEstimateLink.project_id == project_id)
        .order_by(ProjectEstimateLink.created_at.asc())
    )
    links = result.scalars().all()
    return EstimateLinkListResponse(
        items=[EstimateLinkOut.model_validate(lk) for lk in links],
        total=len(links),
    )
