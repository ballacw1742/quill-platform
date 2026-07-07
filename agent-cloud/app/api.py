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

from app import db as db_mod
from app import jobs as jobs_mod
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


@app.post("/v1/agents/chat")
async def chat(body: ChatIn):
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


@app.post("/v1/agents/subagents", status_code=202)
async def create_subagent(body: SubagentIn) -> SubagentOut:
    """Create + dispatch a sub-agent job (JOBS_BACKEND local|cloudrun)."""
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
