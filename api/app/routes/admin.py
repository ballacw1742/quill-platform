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
from app.services import sentry as sentry_svc
from app.services import scheduler_registry
from app.services.notifications import notifier

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


# ---------------------------------------------------------------------------
# Sprint 2.4 — Notifications + Scheduler admin endpoints
# ---------------------------------------------------------------------------
@router.get("/admin/notifications/test_telegram")
async def test_telegram(
    chat_id: str,
    text: str = "✅ Quill Telegram notification test",
    _: str = Depends(require_admin_header),
) -> dict:
    """Send a test Telegram message via the abstraction. Pass `chat_id=fake`
    to exercise the path without hitting the real Telegram API."""
    res = await notifier.telegram_message(chat_id, text)
    return {
        "ok": res.ok,
        "backend": res.backend,
        "detail": res.detail,
    }


@router.get("/admin/notifications/sentry_test")
async def sentry_test(
    level: str = "warning",
    message: str = "sprint-2.4 sentry test event",
    _: str = Depends(require_admin_header),
) -> dict:
    """Fire a synthetic Sentry event. Returns the event id when DSN is set,
    otherwise `no-dsn`. Useful to verify init wiring without a real DSN."""
    eid = sentry_svc.capture_message(message, level=level, source="admin_test")
    # Also fire an exception capture path for symmetry
    try:
        raise RuntimeError("synthetic sprint-2.4 sentry test exception")
    except RuntimeError as e:
        eid2 = sentry_svc.capture_exception(e, source="admin_test")
    return {
        "ok": True,
        "event_id": eid or "no-dsn",
        "exception_event_id": eid2 or "no-dsn",
    }


@router.get("/admin/scheduler/jobs")
async def list_scheduler_jobs(_: str = Depends(require_admin_header)) -> dict:
    """List scheduler jobs known to the platform.

    Combines the bot's last-heartbeat job snapshot with the canonical
    schedule (so operators see *expected* jobs even if the bot is offline).
    """
    return scheduler_registry.snapshot()


@router.post("/admin/scheduler/jobs/heartbeat")
async def scheduler_heartbeat(
    body: dict,
    _: str = Depends(require_admin_header),
) -> dict:
    """Bot → API heartbeat. Body: `{"jobs": [{id, name, trigger, next_run_at, ...}]}`."""
    jobs = body.get("jobs") or []
    if not isinstance(jobs, list):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "jobs must be a list")
    scheduler_registry.heartbeat(jobs)
    return {"ok": True, "received": len(jobs)}
