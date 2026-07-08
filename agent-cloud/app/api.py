"""FastAPI surface for the orchestrator.

Routes:
  GET  /health            — health + db ping. NOTE: Cloud Run's Google
                            frontend intercepts the literal path `/healthz`
                            on *.run.app and returns its own 404 before the
                            request reaches the container (root-caused in A1
                            — the spike's "GFE 404" caveat). External health
                            checks MUST use /health; /healthz is kept only
                            for container-internal probes.
  GET  /healthz           — same handler (container-internal use only).
  POST /v1/agents/chat    — chat turn. body.stream=true => SSE
                            (events: session, text, tool, done, error).
  GET  /v1/agents           — list tenant agents (A5, WEBCHAT.md §5;
                              provisions tenant + seeds idempotently).
  GET  /v1/agents/sessions      — list tenant sessions (A5, WEBCHAT.md §5).
  GET  /v1/agents/sessions/{id} — full session transcript (A5).
  POST /v1/agents/subagents      — create a sub-agent job (EVENTS.md §jobs).
  GET  /v1/agents/subagents/{id} — job status/result (tenant_id query param).
  POST   /v1/agents/schedules      — create a schedule (A4 cron/reminders).
  GET    /v1/agents/schedules      — list schedules (tenant-scoped).
  GET    /v1/agents/schedules/{id} — one schedule.
  PATCH  /v1/agents/schedules/{id} — enable/disable/update.
  DELETE /v1/agents/schedules/{id} — remove.
  POST /v1/internal/scheduler/tick — Cloud Scheduler entrypoint
                                     (SCHEDULER_BACKEND=cloudscheduler;
                                     X-Agent-Secret auth, never public).
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager

from datetime import datetime

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import agents as agents_mod
from app import approvals as approvals_mod
from app import db as db_mod
from app import directory as directory_mod
from app import jobs as jobs_mod
from app import ratelimit as ratelimit_mod
from app import scheduler as scheduler_mod
from app.config import get_settings
from app.logging_setup import request_id_var, setup_logging
from app.migrations import run_migrations
from app.orchestrator import (
    AgentDisabledError,
    SessionNotFoundError,
    UnknownAgentError,
    chat_turn,
    stream_turn,
)
from app.providers.base import ProviderError

log = logging.getLogger("agentcloud.api")


class ChatIn(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=8000)
    session_id: uuid.UUID | None = None
    stream: bool = False


class SubagentIn(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    task: str = Field(min_length=1, max_length=8000)
    # parent session to wake on completion (optional; must belong to tenant)
    session_id: uuid.UUID | None = None


class SubagentOut(BaseModel):
    job_id: uuid.UUID
    status: str


class ScheduleIn(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    kind: str  # "at" | "cron" (validated in app.scheduler)
    cron_expr: str | None = None
    timezone: str = "UTC"
    run_at: datetime | None = None
    message: str = Field(min_length=1, max_length=8000)
    # optional target session — the fired turn wakes it (reminder delivery)
    session_id: uuid.UUID | None = None
    enabled: bool = True
    delete_after_run: bool = False


class SchedulePatch(BaseModel):
    """PATCH body — absent fields stay unchanged (exclude_unset)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = None
    cron_expr: str | None = None
    timezone: str | None = None
    run_at: datetime | None = None
    message: str | None = Field(default=None, min_length=1, max_length=8000)
    enabled: bool | None = None
    delete_after_run: bool | None = None


class AgentCreateIn(BaseModel):
    """AGENT_BUILDER.md §2.1 — create body (agent CRUD)."""

    tenant_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(min_length=1, max_length=20000)
    model: str | None = None
    tools: list[str] | None = None
    memory_policy: str | None = None
    budget_monthly_usd: float | None = None
    enabled: bool = True


class AgentPatchIn(BaseModel):
    """AGENT_BUILDER.md §2.2 — partial update (absent fields unchanged)."""

    system_prompt: str | None = Field(default=None, min_length=1, max_length=20000)
    model: str | None = None
    tools: list[str] | None = None
    memory_policy: str | None = None
    budget_monthly_usd: float | None = None
    enabled: bool | None = None


class UsageOut(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ChatOut(BaseModel):
    session_id: uuid.UUID
    reply: str
    tool_calls: list[str]
    model: str
    usage: UsageOut
    budget_exceeded: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
    await run_migrations(db_mod.engine)
    if settings.SCHEDULER_BACKEND == "loop":
        scheduler_mod.start_loop()
    log.info(
        "agentcloud started",
        extra={
            "extra_fields": {
                "model_provider": settings.MODEL_PROVIDER,
                "model_default": settings.MODEL_DEFAULT,
                "scheduler_backend": settings.SCHEDULER_BACKEND,
            }
        },
    )
    yield
    await scheduler_mod.stop_loop()
    await db_mod.dispose()


app = FastAPI(title="quill-agent-orchestrator", lifespan=lifespan)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
    request_id_var.set(rid)
    response = await call_next(request)
    response.headers["X-Request-Id"] = rid
    return response


def _health_payload_status() -> tuple[dict, int]:
    settings = get_settings()
    return (
        {
            "ok": True,
            "service": settings.SERVICE_NAME,
            "model_provider": settings.MODEL_PROVIDER,
        },
        200,
    )


@app.get("/health")
@app.get("/healthz")  # container-internal only — GFE swallows /healthz on *.run.app
async def health():
    payload, _ = _health_payload_status()
    db_ok = await db_mod.ping()
    payload["db"] = "up" if db_ok else "down"
    if not db_ok:
        payload["ok"] = False
        return JSONResponse(payload, status_code=503)
    return payload


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _rate_limit_response(exc: ratelimit_mod.RateLimitExceeded) -> HTTPException:
    """429 with Retry-After (LIMITS.md §3 rejection shape)."""
    return HTTPException(
        status_code=429,
        detail=exc.detail,
        headers={"Retry-After": str(exc.decision.retry_after_seconds)},
    )


@app.post("/v1/agents/chat")
async def chat(body: ChatIn):
    # Per-tenant rate limit checked BEFORE the stream starts, so an over-limit
    # chat is a plain HTTP 429, never an SSE error event (LIMITS.md §3).
    try:
        await ratelimit_mod.enforce(body.tenant_id, "chat")
    except ratelimit_mod.RateLimitExceeded as exc:
        raise _rate_limit_response(exc) from exc
    if body.stream:
        async def gen():
            try:
                async for ev in stream_turn(
                    tenant_id=body.tenant_id,
                    agent_id=body.agent_id,
                    message=body.message,
                    session_id=body.session_id,
                    use_stream=True,
                ):
                    ev_type = ev.pop("type")
                    yield _sse(ev_type, ev)
            except (UnknownAgentError, SessionNotFoundError) as exc:
                yield _sse("error", {"detail": str(exc), "status": 404})
            except AgentDisabledError as exc:
                yield _sse("error", {"detail": str(exc), "status": 403})
            except ProviderError as exc:
                log.error("provider error (stream): %s", exc)
                yield _sse("error", {"detail": str(exc), "status": 502})
            except Exception:
                log.exception("unhandled error in SSE stream")
                yield _sse("error", {"detail": "internal error", "status": 500})

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = await chat_turn(
            tenant_id=body.tenant_id,
            agent_id=body.agent_id,
            message=body.message,
            session_id=body.session_id,
        )
    except (UnknownAgentError, SessionNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except AgentDisabledError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ProviderError as exc:
        log.error("provider error: %s", exc)
        raise HTTPException(502, str(exc)) from exc
    return ChatOut(
        session_id=result.session_id,
        reply=result.reply,
        tool_calls=result.tool_calls,
        model=result.model,
        usage=UsageOut(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
        ),
        budget_exceeded=result.budget_exceeded,
    )


@app.get("/v1/agents/usage")
async def get_usage(tenant_id: str):
    """Current-month usage/meters for a tenant (LIMITS.md §2). Provisions the
    tenant + seed agents idempotently first, so a fresh tenant returns a
    well-formed zero-usage report."""
    return await directory_mod.get_usage(tenant_id)


@app.get("/v1/agents")
async def list_agents(tenant_id: str, limit: int = 100, offset: int = 0):
    """Tenant agent directory (WEBCHAT.md §3.1). Idempotently provisions the
    tenant + seed agents first so a fresh tenant sees `personal` + `quill`
    before its first chat turn."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    return await directory_mod.list_agents(tenant_id, limit=limit, offset=offset)


@app.get("/v1/agents/sessions")
async def list_sessions(
    tenant_id: str, agent_id: str | None = None, limit: int = 50, offset: int = 0
):
    """Tenant sessions, newest-updated first (WEBCHAT.md §3.2)."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return await directory_mod.list_sessions(
        tenant_id, agent_id=agent_id, limit=limit, offset=offset
    )


@app.get("/v1/agents/sessions/{session_id}")
async def get_session_transcript(session_id: uuid.UUID, tenant_id: str):
    """Full transcript (WEBCHAT.md §3.3); 404 unknown/cross-tenant."""
    try:
        return await directory_mod.get_transcript(tenant_id, session_id)
    except directory_mod.DirectorySessionNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/v1/agents/subagents", status_code=202)
async def create_subagent(body: SubagentIn) -> SubagentOut:
    """Create + dispatch a sub-agent job (JOBS_BACKEND local|cloudrun)."""
    try:
        await ratelimit_mod.enforce(body.tenant_id, "jobs")
    except ratelimit_mod.RateLimitExceeded as exc:
        raise _rate_limit_response(exc) from exc
    try:
        created = await jobs_mod.create_job(
            tenant_id=body.tenant_id,
            agent_id=body.agent_id,
            task=body.task,
            parent_session_id=body.session_id,
        )
    except (UnknownAgentError, LookupError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except AgentDisabledError as exc:
        raise HTTPException(403, str(exc)) from exc
    return SubagentOut(job_id=uuid.UUID(created["job_id"]), status=created["status"])


@app.get("/v1/agents/subagents/{job_id}")
async def get_subagent(job_id: uuid.UUID, tenant_id: str):
    """Job status/result. tenant_id is required (same scoping as chat)."""
    try:
        return await jobs_mod.get_job(tenant_id, job_id)
    except jobs_mod.JobNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/v1/agents/schedules", status_code=201)
async def create_schedule(body: ScheduleIn):
    """Create a per-tenant schedule (kind='at' one-shot | 'cron' recurring)."""
    try:
        await ratelimit_mod.enforce(body.tenant_id, "jobs")
    except ratelimit_mod.RateLimitExceeded as exc:
        raise _rate_limit_response(exc) from exc
    try:
        return await scheduler_mod.create_schedule(
            tenant_id=body.tenant_id,
            agent_id=body.agent_id,
            name=body.name,
            kind=body.kind,
            cron_expr=body.cron_expr,
            tz_name=body.timezone,
            run_at=body.run_at,
            message=body.message,
            session_id=body.session_id,
            enabled=body.enabled,
            delete_after_run=body.delete_after_run,
        )
    except scheduler_mod.ScheduleValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (UnknownAgentError, LookupError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except AgentDisabledError as exc:
        raise HTTPException(403, str(exc)) from exc


@app.get("/v1/agents/schedules")
async def list_schedules(tenant_id: str, limit: int = 100, offset: int = 0):
    """List schedules — standard list envelope {items, total, limit, offset}."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    return await scheduler_mod.list_schedules(tenant_id, limit=limit, offset=offset)


@app.get("/v1/agents/schedules/{schedule_id}")
async def get_schedule(schedule_id: uuid.UUID, tenant_id: str):
    try:
        return await scheduler_mod.get_schedule(tenant_id, schedule_id)
    except scheduler_mod.ScheduleNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.patch("/v1/agents/schedules/{schedule_id}")
async def patch_schedule(schedule_id: uuid.UUID, tenant_id: str, body: SchedulePatch):
    kwargs = {}
    provided = body.model_dump(exclude_unset=True)
    field_map = {"timezone": "tz_name"}
    for key, value in provided.items():
        kwargs[field_map.get(key, key)] = value
    try:
        return await scheduler_mod.update_schedule(tenant_id, schedule_id, **kwargs)
    except scheduler_mod.ScheduleValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    except scheduler_mod.ScheduleNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.delete("/v1/agents/schedules/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: uuid.UUID, tenant_id: str):
    try:
        await scheduler_mod.delete_schedule(tenant_id, schedule_id)
    except scheduler_mod.ScheduleNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


# ---------------------------------------------------------------------------
# Agent Builder CRUD (Phase C, AGENT_BUILDER.md §2). NOTE ROUTE ORDER: the
# static /v1/agents/{catalog,templates} + the CRUD literal routes are declared
# above the {agent_id} path-param routes so a literal (usage/sessions/
# subagents/schedules/catalog/templates) is never shadowed by {agent_id}.
# ---------------------------------------------------------------------------


@app.get("/v1/agents/catalog")
async def agents_catalog():
    """Tool-palette catalog + allowed models + memory policies
    (AGENT_BUILDER.md §5). Static; tenant-independent."""
    return agents_mod.tool_catalog()


@app.get("/v1/agents/templates")
async def agents_templates():
    """Clone-to-create starter templates (AGENT_BUILDER.md §6). Static."""
    return agents_mod.templates()


def _agent_crud_error(exc: Exception) -> HTTPException:
    if isinstance(exc, agents_mod.SeedProtectedError):
        return HTTPException(403, str(exc))
    if isinstance(exc, agents_mod.AgentConflictError):
        return HTTPException(409, str(exc))
    if isinstance(exc, agents_mod.AgentValidationError):
        return HTTPException(400, str(exc))
    if isinstance(exc, agents_mod.AgentNotFoundError):
        return HTTPException(404, str(exc))
    raise exc  # pragma: no cover


@app.post("/v1/agents", status_code=201)
async def create_agent(body: AgentCreateIn):
    """Create an agent definition (AGENT_BUILDER.md §2.1)."""
    data = body.model_dump(exclude_unset=True)
    tenant_id = data.pop("tenant_id")
    try:
        return await agents_mod.create_agent(tenant_id, data)
    except (
        agents_mod.AgentValidationError,
        agents_mod.AgentConflictError,
    ) as exc:
        raise _agent_crud_error(exc) from exc


@app.get("/v1/agents/{agent_id}")
async def get_agent(agent_id: str, tenant_id: str):
    """Agent-definition detail (AGENT_BUILDER.md §2); 404 unknown/cross-tenant."""
    try:
        return await agents_mod.get_agent(tenant_id, agent_id)
    except agents_mod.AgentNotFoundError as exc:
        raise _agent_crud_error(exc) from exc


@app.patch("/v1/agents/{agent_id}")
async def patch_agent(agent_id: str, tenant_id: str, body: AgentPatchIn):
    """Partial update (AGENT_BUILDER.md §2.2). Seed-protected fields → 403."""
    patch = body.model_dump(exclude_unset=True)
    try:
        return await agents_mod.update_agent(tenant_id, agent_id, patch)
    except (
        agents_mod.AgentValidationError,
        agents_mod.SeedProtectedError,
        agents_mod.AgentNotFoundError,
    ) as exc:
        raise _agent_crud_error(exc) from exc


@app.delete("/v1/agents/{agent_id}")
async def delete_agent(agent_id: str, tenant_id: str):
    """Soft-delete (disable) an agent (AGENT_BUILDER.md §2). Seeds → 403.
    History is never hard-deleted."""
    try:
        return await agents_mod.delete_agent(tenant_id, agent_id)
    except (
        agents_mod.SeedProtectedError,
        agents_mod.AgentNotFoundError,
    ) as exc:
        raise _agent_crud_error(exc) from exc


class ApprovalNotifyIn(BaseModel):
    """api → agent-cloud resolution push (APPROVALS.md §6)."""

    approval_id: str = Field(min_length=1, max_length=128)
    workflow: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=32)  # Quill ApprovalStatus
    tenant_id: str = Field(min_length=1, max_length=128)
    proposal_id: str | None = None
    external_ref: str | None = None
    error: str | None = None


@app.post("/v1/internal/approvals/notify")
async def approvals_notify(body: ApprovalNotifyIn, x_agent_secret: str = Header(default="")):
    """Best-effort resolution push from the Quill api approvals executor.

    Auth: X-Agent-Secret must equal APPROVALS_NOTIFY_SECRET (same
    403-when-unset pattern as the scheduler tick). Idempotent: a proposal
    already finalized (e.g. by the reconcile sweep) is a no-op.
    """
    secret = get_settings().APPROVALS_NOTIFY_SECRET
    if not secret or x_agent_secret != secret:
        raise HTTPException(403, "approvals notify: invalid or missing X-Agent-Secret")
    mapped = approvals_mod.QUILL_STATUS_MAP.get(body.status)
    if mapped is None:
        raise HTTPException(400, f"non-terminal approval status {body.status!r}")
    finalized = await approvals_mod.finalize_proposal(
        tenant_id=body.tenant_id,
        quill_approval_id=body.approval_id,
        status=mapped,
        external_ref=body.external_ref,
        error=body.error,
        source="notify",
    )
    return {"finalized": finalized, "status": mapped}


@app.post("/v1/internal/scheduler/tick")
async def scheduler_tick(x_agent_secret: str = Header(default="")):
    """Cloud Scheduler entrypoint (SCHEDULER_BACKEND=cloudscheduler).

    Auth: X-Agent-Secret must equal SCHEDULER_TICK_SECRET (same internal
    shared-secret pattern as the Quill tool suite). Unset secret ⇒ endpoint
    is disabled (403) — the loop backend needs no HTTP entrypoint. Deploy
    behind IAM/OIDC-gated ingress; never expose publicly (README).
    """
    secret = get_settings().SCHEDULER_TICK_SECRET
    if not secret or x_agent_secret != secret:
        raise HTTPException(403, "scheduler tick: invalid or missing X-Agent-Secret")
    return await scheduler_mod.tick()
