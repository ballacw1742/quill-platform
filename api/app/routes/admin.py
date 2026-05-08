"""Admin routes — Charles-only. Sprint 1 gates with X-Admin header."""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db import get_db
from app.enums import ApprovalStatus
from app.models import AgentRegistration, ApprovalItem, AuditLogEntry, User
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
from app.services import scheduler_registry
from app.services import sentry as sentry_svc
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
# Sprint 2.3 — Offsite mirror + nightly chain verification admin endpoints
# ---------------------------------------------------------------------------
_VERIFY_JOBS: dict[str, dict] = {}


@router.get("/admin/audit/mirror_status")
async def audit_mirror_status(_: str = Depends(require_admin_header)) -> dict:
    """Return live mirror lag, queue depth, mode, and last-mirror metadata."""
    from app.services.audit_mirror import get_mirror

    return get_mirror().get_status()


@router.get("/admin/audit/verifications/recent")
async def audit_verifications_recent(
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_header),
) -> list[dict]:
    from app.models import AuditChainVerification
    from app.services import audit_verify as verify_svc

    rows = await verify_svc.list_recent_verifications(db, limit=limit)

    def _row_dict(r: AuditChainVerification) -> dict:
        return {
            "id": r.id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "duration_ms": r.duration_ms,
            "scope": r.scope,
            "scope_ref": r.scope_ref,
            "result": r.result,
            "chain_length_postgres": r.chain_length_postgres,
            "chain_length_mirror": r.chain_length_mirror,
            "last_hash_postgres": r.last_hash_postgres,
            "last_hash_mirror": r.last_hash_mirror,
            "triggered_by": r.triggered_by,
            "details": r.details,
        }

    return [_row_dict(r) for r in rows]


@router.post("/admin/audit/verify_now")
async def audit_verify_now(
    body: dict | None = None,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_header),
) -> dict:
    """Kick off an ad-hoc verification. Runs synchronously here (the chain is
    small in Sprint 2.3); returns a job_id you can poll for parity with the
    async API contract."""
    import uuid as _uuid

    from app.services import audit_verify as verify_svc

    body = body or {}
    approval_id = body.get("approval_id")
    job_id = str(_uuid.uuid4())
    _VERIFY_JOBS[job_id] = {"status": "running", "result": None}
    try:
        if approval_id:
            result = await verify_svc.verify_per_approval(
                db, approval_id, triggered_by="admin_api"
            )
        else:
            result = await verify_svc.verify_full_chain(db, triggered_by="admin_api")
        _VERIFY_JOBS[job_id] = {"status": "done", "result": result}
    except Exception as exc:  # noqa: BLE001
        _VERIFY_JOBS[job_id] = {
            "status": "error",
            "result": {"error": f"{type(exc).__name__}: {exc}"},
        }
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    return {"job_id": job_id, "status": "done"}


@router.get("/admin/audit/verify_job/{job_id}")
async def audit_verify_job_status(
    job_id: str, _: str = Depends(require_admin_header)
) -> dict:
    job = _VERIFY_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return {"job_id": job_id, **job}


@router.post("/admin/audit/clear_freeze")
async def audit_clear_freeze(_: str = Depends(require_admin_header)) -> dict:
    """Operator override: remove the audit-freeze touch-file after triage."""
    from app.services import audit_verify as verify_svc

    cleared = verify_svc.clear_freeze_flag()
    return {"ok": True, "cleared": cleared}


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


@router.post("/admin/users/telegram_pair")
async def telegram_pair(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_header),
) -> dict:
    """Pair a Telegram chat to a Quill user account.

    The bot validates the `/start <code>` code itself (HMAC of email +
    timestamp using TELEGRAM_PAIRING_SECRET). On success it calls this
    endpoint with the resolved email + chat_id so the User row is updated.

    Body: `{"email": "...", "chat_id": "...", "telegram_username": "..."}`.
    Backwards-compat: if `code` is provided instead of `email`, we treat it
    as the email (legacy clients).
    """
    email = body.get("email") or body.get("code")
    chat_id = body.get("chat_id")
    if not email or not chat_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "email + chat_id required")
    res = await db.execute(select(User).where(User.email == email))
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {email!r} not found")
    user.telegram_chat_id = str(chat_id)
    await db.commit()
    return {
        "ok": True,
        "user_id": user.id,
        "email": user.email,
        "telegram_chat_id": user.telegram_chat_id,
    }
