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
from app import models_dev_chat as _models_dev_chat  # noqa: F401 — registers dev-chat ORM models with Base.metadata
from app import models_requests as _models_requests  # noqa: F401 — registers project_requests ORM model with Base.metadata
from app import models_projects as _models_projects  # noqa: F401 — registers projects ORM model with Base.metadata
from app.routes import admin, approvals, audit, auth, contracts, dev_chat, documents, estimates, realtime, requests as requests_routes, sites as sites_routes, projects as projects_routes
from app.services import sentry as sentry_svc
from app.services.audit_mirror import get_mirror
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
    mirror = get_mirror()
    await mirror.start()
    log.info("audit_mirror started (mode=%s)", mirror.backend.mode)
    # Seed the 9 ADK agents into agent_registrations on startup
    try:
        from app.db import SessionLocal as async_session_maker  # noqa: N812
        from app.routes.agents import seed_agents
        async with async_session_maker() as session:
            await seed_agents(session)
    except Exception as _seed_exc:  # noqa: BLE001
        log.warning("agent_seed.failed err=%s", _seed_exc)
    try:
        yield
    finally:
        sla_task.cancel()
        try:
            await sla_task
        except asyncio.CancelledError:
            pass
        await mirror.stop()
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
app.include_router(documents.router)
app.include_router(estimates.router)
app.include_router(realtime.router)
app.include_router(contracts.router)    # Sprint Contracts.1
app.include_router(dev_chat.router)     # Sprint DC.1 dev-chat REST
app.include_router(dev_chat.ws_router)  # Sprint DC.1 dev-chat WS (/ws/dev-chat)
app.include_router(requests_routes.router)  # Requests tab — unified project submission
app.include_router(sites_routes.router)     # Sprint QuillDC — DataSite proxy routes
app.include_router(projects_routes.router)  # Sprint DC.2 — Projects module
# Sprint DC.4: Agent Registry routes are in admin.py (GET/PATCH /v1/agents). Seed on startup via lifespan.
