"""Sub-agent jobs (design doc §3.4; contract in EVENTS.md).

A job = one background agent turn in its own fresh session, budget-metered
through the exact same (tenant, agent, day) usage rows as interactive chat.

Lifecycle: create (queued) → dispatch per JOBS_BACKEND → run (running,
subagent.started) → chat_turn via the orchestrator → finalize
(ok|error, result/error JSONB, subagent.completed|failed, parent wake).

Backends (config-gated like MODEL_PROVIDER):
  - "local": asyncio task in this process (dev/tests). Tracked in
    _local_tasks so the loop keeps a strong reference.
  - "cloudrun": one Cloud Run Job execution of CLOUDRUN_JOB_NAME with
    JOB_ID/JOB_TENANT_ID env overrides; the container runs
    `python -m app.jobs run <job_id>` (this module's CLI).

The wake insert shares the finalization transaction (see EVENTS.md), so a
finalized job always has exactly one wake in the parent session.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import sqlalchemy as sa

from app import events as events_mod
from app.config import get_settings
from app.db import admin_session, tenant_session
from app.models import Job, Message, Session
from app.providers import ModelProvider

log = logging.getLogger("agentcloud.jobs")

JOB_STATUSES = ("queued", "running", "ok", "error", "timeout")

_local_tasks: set[asyncio.Task] = set()

# Injectable for tests (mirrors PubSubBus client_factory pattern).
_cloudrun_client_factory: Callable[[], Any] | None = None


class JobNotFoundError(LookupError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _preview(text: str, limit: int = 200) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def job_dict(job: Job) -> dict[str, Any]:
    return {
        "job_id": str(job.job_id),
        "tenant_id": job.tenant_id,
        "agent_id": job.agent_id,
        "parent_session_id": str(job.parent_session_id) if job.parent_session_id else None,
        "session_id": str(job.session_id) if job.session_id else None,
        "task": job.task,
        "status": job.status,
        "result": job.result,
        "error": job.error,
        "created_at": str(job.created_at),
        "started_at": str(job.started_at) if job.started_at else None,
        "finished_at": str(job.finished_at) if job.finished_at else None,
    }


async def create_job(
    *,
    tenant_id: str,
    agent_id: str,
    task: str,
    parent_session_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Insert a queued job row and dispatch it per JOBS_BACKEND.

    Agent + parent session are validated here (same 404/403 semantics as
    /v1/agents/chat) — first contact provisions the tenant + seed agents,
    exactly like the orchestrator's _prepare.
    """
    from app.orchestrator import (  # noqa: PLC0415 — avoid import cycle
        AgentDisabledError,
        UnknownAgentError,
        _insert_ignore,
    )
    from app.models import AgentDef, Tenant  # noqa: PLC0415
    from app.seeds import SEED_AGENTS, seed_model_for_tenant  # noqa: PLC0415

    s = get_settings()
    task = (task or "").strip()[: s.SUBAGENT_TASK_MAX_CHARS]
    job_id = uuid.uuid4()
    async with tenant_session(tenant_id) as db:
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
        await db.execute(_insert_ignore(Tenant, {"tenant_id": tenant_id}, dialect))
        seed_model = seed_model_for_tenant(tenant_id)
        for seed in SEED_AGENTS:
            await db.execute(
                _insert_ignore(
                    AgentDef,
                    {
                        "tenant_id": tenant_id,
                        "agent_id": seed.agent_id,
                        "system_prompt": seed.system_prompt.format(tenant_id=tenant_id),
                        "model": seed_model,
                        "tools": list(seed.tools),
                        "budget_monthly_usd": s.DEFAULT_BUDGET_MONTHLY_USD,
                        "enabled": True,
                        "memory_policy": seed.memory_policy,
                    },
                    dialect,
                )
            )
        agent = (
            await db.execute(
                sa.select(AgentDef).where(
                    AgentDef.tenant_id == tenant_id, AgentDef.agent_id == agent_id
                )
            )
        ).scalar_one_or_none()
        if agent is None:
            raise UnknownAgentError(f"agent {agent_id!r} is not defined for this tenant")
        if not agent.enabled:
            raise AgentDisabledError(f"agent {agent_id!r} is disabled")
        if parent_session_id is not None:
            sess = (
                await db.execute(
                    sa.select(Session.session_id).where(
                        Session.session_id == parent_session_id,
                        Session.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if sess is None:
                raise LookupError("parent session not found for this tenant")
        db.add(
            Job(
                job_id=job_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                parent_session_id=parent_session_id,
                task=task,
                status="queued",
                payload={"task": task},
            )
        )
    await _dispatch(job_id, tenant_id)
    return {"job_id": str(job_id), "status": "queued"}


async def get_job(tenant_id: str, job_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as db:
        job = (
            await db.execute(
                sa.select(Job).where(Job.job_id == job_id, Job.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if job is None:
            raise JobNotFoundError("job not found for this tenant")
        return job_dict(job)


async def _dispatch(job_id: uuid.UUID, tenant_id: str) -> None:
    backend = get_settings().JOBS_BACKEND
    if backend == "local":
        task = asyncio.create_task(run_job(job_id, tenant_id))
        _local_tasks.add(task)
        task.add_done_callback(_local_tasks.discard)
    elif backend == "cloudrun":
        await _launch_cloudrun(job_id, tenant_id)
    else:
        raise ValueError(f"unknown JOBS_BACKEND {backend!r} (local|cloudrun)")


def _get_cloudrun_client():
    if _cloudrun_client_factory is not None:
        return _cloudrun_client_factory()
    from google.cloud import run_v2  # noqa: PLC0415  # pragma: no cover

    return run_v2.JobsAsyncClient()  # pragma: no cover


async def _launch_cloudrun(job_id: uuid.UUID, tenant_id: str) -> None:
    """Fire one Cloud Run Job execution carrying the job id via env.

    The job resource (CLOUDRUN_JOB_NAME) is created ops-side with this
    service's image + DATABASE_URL/API-key secrets and
    `--command python --args -m,app.jobs,run` (see README). We only override
    env per execution.
    """
    s = get_settings()
    client = _get_cloudrun_client()
    name = (
        f"projects/{s.CLOUDRUN_JOB_PROJECT}/locations/{s.CLOUDRUN_JOB_REGION}"
        f"/jobs/{s.CLOUDRUN_JOB_NAME}"
    )
    request = {
        "name": name,
        "overrides": {
            "container_overrides": [
                {
                    "env": [
                        {"name": "JOB_ID", "value": str(job_id)},
                        {"name": "JOB_TENANT_ID", "value": tenant_id},
                    ],
                    "args": ["-m", "app.jobs", "run", str(job_id)],
                }
            ]
        },
    }
    await client.run_job(request=request)
    log.info(
        "cloudrun job execution launched",
        extra={"extra_fields": {"job_id": str(job_id), "job_name": name}},
    )


async def run_job(
    job_id: uuid.UUID,
    tenant_id: str,
    *,
    provider: ModelProvider | None = None,
) -> dict[str, Any]:
    """Execute one job to completion. Returns the final job dict."""
    # -- claim: queued → running (idempotency guard: a finalized or already-
    # running job is not re-run) + durable subagent.started ------------------
    async with tenant_session(tenant_id) as db:
        job = (
            await db.execute(
                sa.select(Job).where(Job.job_id == job_id, Job.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if job is None:
            raise JobNotFoundError("job not found for this tenant")
        if job.status != "queued":
            log.warning(
                "job %s not queued (status=%s) — skipping re-run", job_id, job.status
            )
            return job_dict(job)
        job.status = "running"
        job.started_at = _utcnow()
        agent_id = job.agent_id
        task = job.task
        parent_session_id = job.parent_session_id
        started_ev = events_mod.make_event(
            tenant_id=tenant_id,
            agent_id=agent_id,
            type="subagent.started",
            payload={"job_id": str(job_id), "task_preview": _preview(task)},
        )
        events_mod.record_events(db, [started_ev])
    await events_mod.emit([started_ev])

    # -- run: a normal orchestrator turn in a fresh sub-session. Budget rows,
    # refusal semantics, tool allow-lists — identical to interactive chat. ---
    from app.orchestrator import chat_turn  # noqa: PLC0415 — avoid import cycle

    try:
        result = await chat_turn(
            tenant_id=tenant_id, agent_id=agent_id, message=task, provider=provider
        )
        final_status = "ok"
        result_json: dict[str, Any] = {
            "reply": result.reply,
            "session_id": str(result.session_id),
            "tool_calls": result.tool_calls,
            "usage": {
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": round(result.cost_usd, 6),
            },
            "budget_exceeded": result.budget_exceeded,
        }
        error_text: str | None = None
        sub_session_id: uuid.UUID | None = result.session_id
        done_ev = events_mod.make_event(
            tenant_id=tenant_id,
            agent_id=agent_id,
            session_id=result.session_id,
            type="subagent.completed",
            payload={
                "job_id": str(job_id),
                "reply_preview": _preview(result.reply),
                "budget_exceeded": result.budget_exceeded,
                "cost_usd": round(result.cost_usd, 6),
            },
        )
        wake_body = f"Result: {result.reply}"
        wake_verb = "completed"
    except Exception as exc:  # noqa: BLE001 — job must always finalize
        log.exception("subagent job %s failed", job_id)
        final_status = "error"
        result_json = {}
        error_text = f"{type(exc).__name__}: {exc}"
        sub_session_id = None
        done_ev = events_mod.make_event(
            tenant_id=tenant_id,
            agent_id=agent_id,
            type="subagent.failed",
            payload={"job_id": str(job_id), "error": error_text},
        )
        wake_body = f"Error: {error_text}"
        wake_verb = "failed"

    # -- finalize: job row + durable event + parent wake in ONE tx ----------
    async with tenant_session(tenant_id) as db:
        await db.execute(
            sa.update(Job)
            .where(Job.job_id == job_id, Job.tenant_id == tenant_id)
            .values(
                status=final_status,
                result=result_json or None,
                error=error_text,
                session_id=sub_session_id,
                finished_at=_utcnow(),
            )
        )
        events_mod.record_events(db, [done_ev])
        if parent_session_id is not None:
            wake_text = (
                f"[system wake] Sub-agent job {job_id} (agent {agent_id}) {wake_verb}.\n"
                f"Task: {_preview(task)}\n{wake_body}"
            )
            db.add(
                Message(
                    session_id=parent_session_id,
                    tenant_id=tenant_id,
                    role="user",
                    content=[{"type": "text", "text": wake_text}],
                )
            )
            await db.execute(
                sa.update(Session)
                .where(
                    Session.session_id == parent_session_id,
                    Session.tenant_id == tenant_id,
                )
                .values(updated_at=_utcnow())
            )
    await events_mod.emit([done_ev])
    log.info(
        "subagent job finalized",
        extra={"extra_fields": {"job_id": str(job_id), "status": final_status}},
    )
    return await get_job(tenant_id, job_id)


async def _resolve_tenant(job_id: uuid.UUID) -> str:
    """CLI helper: find a job's tenant. Prefers JOB_TENANT_ID env; falls back
    to an admin-policy lookup (maintenance path, same as app/admin.py)."""
    import os  # noqa: PLC0415

    env_tenant = os.environ.get("JOB_TENANT_ID", "")
    if env_tenant:
        return env_tenant
    async with admin_session() as db:
        tenant = (
            await db.execute(sa.select(Job.tenant_id).where(Job.job_id == job_id))
        ).scalar_one_or_none()
    if tenant is None:
        raise JobNotFoundError(f"job {job_id} not found")
    return tenant


async def _cli_run(job_id_str: str) -> int:
    """`python -m app.jobs run <job_id>` — the Cloud Run Job entrypoint."""
    from app import db as db_mod  # noqa: PLC0415
    from app.logging_setup import setup_logging  # noqa: PLC0415
    from app.migrations import run_migrations  # noqa: PLC0415

    setup_logging(get_settings().LOG_LEVEL)
    job_id = uuid.UUID(job_id_str)
    await run_migrations(db_mod.engine)
    try:
        tenant_id = await _resolve_tenant(job_id)
        final = await run_job(job_id, tenant_id)
        print(f"job {job_id} finished: {final['status']}")
        return 0 if final["status"] == "ok" else 1
    finally:
        await db_mod.dispose()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover — thin CLI
    import sys  # noqa: PLC0415

    args = argv if argv is not None else sys.argv[1:]
    if len(args) == 2 and args[0] == "run":
        return asyncio.run(_cli_run(args[1]))
    print("usage: python -m app.jobs run <job_id>")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
