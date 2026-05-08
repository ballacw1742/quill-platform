"""FastAPI bootstrap: middleware, routes, lifespan."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.config import get_settings
from app.db import connect, disconnect
from app.logging_setup import configure_logging
from app.routes import admin, approvals, audit, auth, realtime
from app.services import sentry as sentry_svc
from app.services.sla import run_forever as sla_run_forever

_settings = get_settings()
configure_logging(_settings.LOG_LEVEL)
log = logging.getLogger("quill.main")

# Initialize Sentry once at module import time. Safe even with no DSN —
# the wrapper just installs scope tags. We re-call inside lifespan in case
# the env was loaded after import.
sentry_svc.init()


@asynccontextmanager
async def lifespan(app: FastAPI):
    sentry_svc.init()
    await connect()
    log.info("db connected")
    sla_task = asyncio.create_task(sla_run_forever())
    try:
        yield
    finally:
        sla_task.cancel()
        try:
            await sla_task
        except asyncio.CancelledError:
            pass
        await disconnect()
        log.info("db disconnected")


app = FastAPI(
    title="Quill Platform API",
    description="Approval Queue backend for the Agentic PMO.",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = rid
    sentry_svc.tag_request(rid)
    try:
        response = await call_next(request)
    except Exception as e:  # noqa: BLE001
        log.exception("unhandled error", extra={"request_id": rid})
        sentry_svc.capture_exception(e, request_id=rid)
        return JSONResponse(
            status_code=500,
            content={"detail": "internal error", "request_id": rid},
            headers={"x-request-id": rid},
        )
    response.headers["x-request-id"] = rid
    return response


@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "service": "quill-platform-api",
        "version": __version__,
        "docs": "/docs",
        "health": "/v1/admin/health",
    }


# Routes
app.include_router(approvals.router)
app.include_router(audit.router)
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(realtime.router)
