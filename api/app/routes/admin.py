"""Admin routes — Charles-only. Sprint 1 gates with X-Admin header."""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db import get_db
from app.enums import ApprovalStatus
from app.models import AgentRegistration, ApprovalItem, AuditLogEntry
from app.schemas import (
    AgentOut,
    AgentUpdate,
    AuditVerifyResult,
    HealthOut,
    LitigationHoldRequest,
)
from app.security import require_admin_header
from app.services import approvals as svc
from app.services import audit as audit_svc

router = APIRouter(prefix="/v1", tags=["admin"])


@router.get("/agents", response_model=list[AgentOut])
async def list_agents(db: AsyncSession = Depends(get_db)) -> list[AgentOut]:
    res = await db.execute(select(AgentRegistration).order_by(AgentRegistration.agent_id))
    return [AgentOut.model_validate(a) for a in res.scalars().all()]


@router.post(
    "/agents/{agent_id}",
    response_model=AgentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register an agent (idempotent upsert)",
)
async def register_agent(
    agent_id: str,
    body: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_header),
) -> AgentOut:
    """Idempotent agent registration. If a row exists, it is patched; otherwise created.

    The runtime calls this once per agent on bootstrap so the AgentRegistration
    table is populated before any approvals flow.
    """
    data = body.model_dump(exclude_none=True)
    agent = await db.get(AgentRegistration, agent_id)
    if agent is None:
        agent = AgentRegistration(agent_id=agent_id)
        db.add(agent)
    for k, v in data.items():
        setattr(agent, k, v.value if hasattr(v, "value") else v)
    await db.commit()
    await db.refresh(agent)
    return AgentOut.model_validate(agent)


@router.patch("/agents/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: str,
    body: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_header),
) -> AgentOut:
    agent = await db.get(AgentRegistration, agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not registered")
    data = body.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(agent, k, v.value if hasattr(v, "value") else v)
    await db.commit()
    await db.refresh(agent)
    return AgentOut.model_validate(agent)


@router.post("/admin/litigation_hold/{approval_id}")
async def litigation_hold(
    approval_id: str,
    body: LitigationHoldRequest,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_admin_header),
) -> dict:
    try:
        item = await svc.suspend_for_litigation_hold(
            db, approval_id, actor=actor, reason=body.reason
        )
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    return {"ok": True, "id": item.id, "status": item.status}


@router.get("/admin/health", response_model=HealthOut)
async def health(db: AsyncSession = Depends(get_db)) -> HealthOut:
    db_ok = "ok"
    try:
        pending = (
            await db.execute(
                select(func.count(ApprovalItem.id)).where(
                    ApprovalItem.status == ApprovalStatus.PENDING.value
                )
            )
        ).scalar_one()
        executed = (
            await db.execute(
                select(func.count(ApprovalItem.id)).where(
                    ApprovalItem.status == ApprovalStatus.EXECUTED.value
                )
            )
        ).scalar_one()
        chain_count = (
            await db.execute(select(func.count(AuditLogEntry.id)))
        ).scalar_one()
    except Exception:  # noqa: BLE001
        db_ok = "fail"
        pending = 0
        executed = 0
        chain_count = 0

    audit_status = "empty"
    if chain_count > 0:
        # Quick global chain verify (cheap for Sprint 1; future: incremental).
        verified = await audit_svc.verify_chain(db, None)
        audit_status = "ok" if verified["ok"] else "broken"

    # Count SLA breaches still open (pending past sla_due_at)
    from datetime import datetime

    now = datetime.now(UTC)
    sla_breaches = (
        await db.execute(
            select(func.count(ApprovalItem.id)).where(
                ApprovalItem.status == ApprovalStatus.PENDING.value,
                ApprovalItem.sla_due_at.is_not(None),
                ApprovalItem.sla_due_at < now,
            )
        )
    ).scalar_one()

    return HealthOut(
        ok=(db_ok == "ok"),
        db=db_ok,  # type: ignore[arg-type]
        queue_depth_pending=pending,
        queue_depth_executed=executed,
        audit_chain=audit_status,  # type: ignore[arg-type]
        audit_chain_length=chain_count,
        sla_breaches_open=sla_breaches,
        version=__version__,
    )


@router.post("/admin/audit_verify", response_model=AuditVerifyResult)
async def audit_verify(
    db: AsyncSession = Depends(get_db), _: str = Depends(require_admin_header)
) -> AuditVerifyResult:
    result = await audit_svc.verify_chain(db, None)
    return AuditVerifyResult(**result)
