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
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import db as db_mod
from app import jobs as jobs_mod
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
    log.info(
        "agentcloud started",
        extra={
            "extra_fields": {
                "model_provider": settings.MODEL_PROVIDER,
                "model_default": settings.MODEL_DEFAULT,
            }
        },
    )
    yield
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
