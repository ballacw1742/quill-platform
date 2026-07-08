"""Agent Cloud bridge routes — Sprint A5 (agent-cloud/WEBCHAT.md) +
Sprint B1 per-user tenancy (agent-cloud/TENANCY.md).

Authenticated Quill-web-facing endpoints that forward to the agent-cloud
orchestrator (quill-agent-orchestrator service). Same proxy conventions as
the /v1/sites DataSite proxy, with two hard rules from WEBCHAT.md:

  1. tenant_id is derived server-side — never read from the client. Any
     client-sent tenant_id is not even a schema field. Since B1
     (TENANCY.md §1) the derivation is per-user:
         workspace=personal (default) → "user-{user.id}"
         workspace=org               → settings.AGENTCLOUD_TENANT_ID,
                                        owner/partner roles only (else 403).
     `workspace` is a two-value enum, not a tenant id — the client still
     cannot name an arbitrary tenant.
  2. Browser auth is the normal Quill JWT (get_current_user). No
     X-Agent-Secret ever reaches the browser; Quill API → agent-cloud is
     protected at the network/IAM layer like the DataSite proxy.

Endpoints (WEBCHAT.md §3):
  GET  /v1/agent-cloud/agents            — tenant agent directory
  GET  /v1/agent-cloud/usage             — current-month usage/meters (B2)
  GET  /v1/agent-cloud/sessions          — session list (optional agent_id)
  GET  /v1/agent-cloud/sessions/{id}     — full transcript
  POST /v1/agent-cloud/chat              — chat turn; stream=true ⇒ SSE
                                           passthrough, else JSON
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from enum import Enum
from typing import AsyncIterator, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.enums import UserRole
from app.security import get_current_user

log = logging.getLogger("quill.agent_cloud")

router = APIRouter(prefix="/v1/agent-cloud", tags=["agent-cloud"])

# Tests override this with an httpx.ASGITransport wired to a fake
# agent-cloud app; production leaves it None (real network transport).
TRANSPORT_OVERRIDE: Optional[httpx.AsyncBaseTransport] = None

_UNREACHABLE_DETAIL = "agent service unreachable"
_ORG_FORBIDDEN_DETAIL = "org workspace requires owner or partner role"


class Workspace(str, Enum):
    """TENANCY.md §1 — server-side tenant selector. Never a raw tenant id."""

    personal = "personal"
    org = "org"


def tenant_for_user(user_id: str) -> str:
    """The per-user personal tenant id (TENANCY.md §1)."""
    return f"user-{user_id}"


def _resolve_tenant(user, workspace: Workspace) -> str:
    """Derive the agent-cloud tenant from the authenticated user + workspace
    selector. The only two reachable tenants are the caller's own personal
    tenant and (owner/partner only) the shared org tenant."""
    if workspace == Workspace.org:
        if user.role not in (UserRole.OWNER.value, UserRole.PARTNER.value):
            raise HTTPException(status_code=403, detail=_ORG_FORBIDDEN_DETAIL)
        return get_settings().AGENTCLOUD_TENANT_ID
    return tenant_for_user(user.id)


async def provision_user_tenant(user_id: str) -> bool:
    """Best-effort signup provisioning hook (TENANCY.md §2).

    Reuses agent-cloud's idempotent provisioning read
    (GET /v1/agents?tenant_id=…). Hard-capped by
    AGENTCLOUD_PROVISION_TIMEOUT_SECONDS and swallows every exception —
    registration must never fail (or hang) because agent-cloud is down.
    Returns True on success (for tests/logging only).
    """
    settings = get_settings()
    tenant_id = tenant_for_user(user_id)
    try:
        async def _call() -> bool:
            async with _client(settings.AGENTCLOUD_PROVISION_TIMEOUT_SECONDS) as client:
                resp = await client.get(
                    "/v1/agents", params={"tenant_id": tenant_id, "limit": 1}
                )
                return resp.status_code < 400

        ok = await asyncio.wait_for(
            _call(), timeout=settings.AGENTCLOUD_PROVISION_TIMEOUT_SECONDS
        )
        if not ok:
            log.warning("agent-cloud provisioning returned an error for %s", tenant_id)
        return ok
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        log.warning("agent-cloud provisioning skipped for %s: %s", tenant_id, exc)
        return False


def _client(timeout: httpx.Timeout | float | None = None) -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=settings.AGENTCLOUD_URL,
        timeout=timeout if timeout is not None else settings.AGENTCLOUD_TIMEOUT_SECONDS,
        transport=TRANSPORT_OVERRIDE,
    )


def _raise_passthrough(resp: httpx.Response) -> None:
    """Re-raise agent-cloud's error envelope ({detail}) with its status."""
    detail: str
    try:
        detail = resp.json().get("detail", resp.text[:300])
    except Exception:  # noqa: BLE001 — non-JSON upstream error body
        detail = resp.text[:300] or f"agent service error ({resp.status_code})"
    raise HTTPException(status_code=resp.status_code, detail=detail)


async def _get_json(path: str, params: dict) -> dict:
    try:
        async with _client() as client:
            resp = await client.get(path, params=params)
    except httpx.HTTPError as exc:
        log.error("agent-cloud unreachable: %s %s (%s)", path, params, exc)
        raise HTTPException(status_code=502, detail=_UNREACHABLE_DETAIL) from exc
    if resp.status_code >= 400:
        _raise_passthrough(resp)
    return resp.json()


async def _request_json(
    method: str, path: str, *, params: dict | None = None, json_body: dict | None = None
) -> dict:
    """Generic proxy for the CRUD verbs (POST/PATCH/DELETE) with identical
    error/502 semantics to _get_json (AGENT_BUILDER.md §8)."""
    try:
        async with _client() as client:
            resp = await client.request(method, path, params=params, json=json_body)
    except httpx.HTTPError as exc:
        log.error("agent-cloud unreachable: %s %s (%s)", method, path, exc)
        raise HTTPException(status_code=502, detail=_UNREACHABLE_DETAIL) from exc
    if resp.status_code >= 400:
        _raise_passthrough(resp)
    return resp.json()


# ---------------------------------------------------------------------------
# Reads (WEBCHAT.md §3.1–3.3)
# ---------------------------------------------------------------------------


@router.get("/agents")
async def list_agents(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    workspace: Workspace = Workspace.personal,
    user=Depends(get_current_user),
):
    tenant_id = _resolve_tenant(user, workspace)
    return await _get_json(
        "/v1/agents",
        {"tenant_id": tenant_id, "limit": limit, "offset": offset},
    )


@router.get("/usage")
async def get_usage(
    workspace: Workspace = Workspace.personal,
    user=Depends(get_current_user),
):
    """Current-month usage/meters for the caller's tenant (LIMITS.md §2).

    Same tenant-derivation + proxy semantics as every other bridge read:
    tenant is server-side from the JWT (workspace=org → owner/partner only),
    502 on unreachable, {detail} envelope passthrough.
    """
    tenant_id = _resolve_tenant(user, workspace)
    return await _get_json("/v1/agents/usage", {"tenant_id": tenant_id})


@router.get("/sessions")
async def list_sessions(
    agent_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    workspace: Workspace = Workspace.personal,
    user=Depends(get_current_user),
):
    params: dict = {
        "tenant_id": _resolve_tenant(user, workspace),
        "limit": limit,
        "offset": offset,
    }
    if agent_id:
        params["agent_id"] = agent_id
    return await _get_json("/v1/agents/sessions", params)


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: uuid.UUID,
    workspace: Workspace = Workspace.personal,
    user=Depends(get_current_user),
):
    return await _get_json(
        f"/v1/agents/sessions/{session_id}",
        {"tenant_id": _resolve_tenant(user, workspace)},
    )


# ---------------------------------------------------------------------------
# Agent Builder CRUD (Phase C, AGENT_BUILDER.md §8). JWT-gated, server-side
# tenant. agent_id is the agent's own id (path/body), never the tenant.
# Client-sent tenant_id is not a schema field anywhere.
# ---------------------------------------------------------------------------


class AgentCreateBody(BaseModel):
    """AGENT_BUILDER.md §2.1. No tenant_id field — derived server-side."""

    agent_id: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(min_length=1, max_length=20000)
    model: str | None = None
    tools: list[str] | None = None
    memory_policy: str | None = None
    budget_monthly_usd: float | None = None
    enabled: bool = True
    workspace: Workspace = Workspace.personal


class AgentPatchBody(BaseModel):
    """AGENT_BUILDER.md §2.2 — partial update; absent fields unchanged."""

    system_prompt: str | None = Field(default=None, min_length=1, max_length=20000)
    model: str | None = None
    tools: list[str] | None = None
    memory_policy: str | None = None
    budget_monthly_usd: float | None = None
    enabled: bool | None = None
    workspace: Workspace = Workspace.personal


@router.get("/catalog")
async def get_catalog(
    workspace: Workspace = Workspace.personal,
    user=Depends(get_current_user),
):
    """Tool-palette catalog + models + memory policies (AGENT_BUILDER.md §5).
    Static upstream; JWT still required (no anonymous access)."""
    _resolve_tenant(user, workspace)  # 403 for observer on workspace=org
    return await _get_json("/v1/agents/catalog", {})


@router.get("/templates")
async def get_templates(
    workspace: Workspace = Workspace.personal,
    user=Depends(get_current_user),
):
    """Clone-to-create starter templates (AGENT_BUILDER.md §6)."""
    _resolve_tenant(user, workspace)
    return await _get_json("/v1/agents/templates", {})


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str,
    workspace: Workspace = Workspace.personal,
    user=Depends(get_current_user),
):
    tenant_id = _resolve_tenant(user, workspace)
    return await _get_json(
        f"/v1/agents/{agent_id}", {"tenant_id": tenant_id}
    )


@router.post("/agents", status_code=201)
async def create_agent(body: AgentCreateBody, user=Depends(get_current_user)):
    tenant_id = _resolve_tenant(user, body.workspace)
    payload = body.model_dump(exclude_unset=True, exclude={"workspace"})
    payload["tenant_id"] = tenant_id  # server-side, always
    return await _request_json("POST", "/v1/agents", json_body=payload)


@router.patch("/agents/{agent_id}")
async def patch_agent(
    agent_id: str, body: AgentPatchBody, user=Depends(get_current_user)
):
    tenant_id = _resolve_tenant(user, body.workspace)
    payload = body.model_dump(exclude_unset=True, exclude={"workspace"})
    return await _request_json(
        "PATCH",
        f"/v1/agents/{agent_id}",
        params={"tenant_id": tenant_id},
        json_body=payload,
    )


@router.delete("/agents/{agent_id}")
async def delete_agent(
    agent_id: str,
    workspace: Workspace = Workspace.personal,
    user=Depends(get_current_user),
):
    tenant_id = _resolve_tenant(user, workspace)
    return await _request_json(
        "DELETE", f"/v1/agents/{agent_id}", params={"tenant_id": tenant_id}
    )


# ---------------------------------------------------------------------------
# Chat (WEBCHAT.md §3.4)
# ---------------------------------------------------------------------------


class AgentChatIn(BaseModel):
    """Client-facing chat body. Deliberately has NO tenant_id field — the
    tenant is derived server-side from the JWT (TENANCY.md §1)."""

    agent_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=8000)
    session_id: uuid.UUID | None = None
    stream: bool = False
    workspace: Workspace = Workspace.personal


async def _sse_passthrough(payload: dict) -> AsyncIterator[bytes]:
    """Byte-for-byte SSE proxy. The upstream client lives inside the
    generator so it stays open for the duration of the stream."""
    try:
        # No read timeout while streaming: a long model turn is legitimate.
        timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
        async with _client(timeout) as client:
            async with client.stream("POST", "/v1/agents/chat", json=payload) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    detail = body.decode("utf-8", "replace")[:300]
                    try:
                        detail = json.loads(detail).get("detail", detail)
                    except Exception:  # noqa: BLE001
                        pass
                    data = json.dumps({"detail": detail, "status": resp.status_code})
                    yield f"event: error\ndata: {data}\n\n".encode()
                    return
                async for chunk in resp.aiter_bytes():
                    yield chunk
    except httpx.HTTPError as exc:
        log.error("agent-cloud SSE proxy failed: %s", exc)
        yield (
            b'event: error\ndata: {"detail": "agent service unreachable", '
            b'"status": 502}\n\n'
        )


@router.post("/chat")
async def chat(body: AgentChatIn, user=Depends(get_current_user)):
    payload: dict = {
        "tenant_id": _resolve_tenant(user, body.workspace),  # server-side, always
        "agent_id": body.agent_id,
        "message": body.message,
        "stream": body.stream,
    }
    if body.session_id is not None:
        payload["session_id"] = str(body.session_id)

    if body.stream:
        return StreamingResponse(
            _sse_passthrough(payload),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        async with _client() as client:
            resp = await client.post("/v1/agents/chat", json=payload)
    except httpx.HTTPError as exc:
        log.error("agent-cloud unreachable (chat): %s", exc)
        raise HTTPException(status_code=502, detail=_UNREACHABLE_DETAIL) from exc
    if resp.status_code >= 400:
        _raise_passthrough(resp)
    return resp.json()


# ---------------------------------------------------------------------------
# Channels (Phase D, CHANNELS.md §12). JWT-gated, server-side tenant. Mirrors
# the agent-cloud pairing/list/revoke surface exactly like the agents CRUD:
# the client never supplies tenant_id (not even a schema field); {detail}
# envelope + 502-on-unreachable passthrough via _request_json/_get_json.
# ---------------------------------------------------------------------------


class ChannelPairBody(BaseModel):
    """CHANNELS.md §12 — mint a pairing code. No tenant_id field: the tenant
    is derived server-side from the JWT (TENANCY.md §1)."""

    agent_id: str = Field(min_length=1, max_length=128)
    platform: str = Field(min_length=1, max_length=32)
    workspace: Workspace = Workspace.personal


@router.post("/channels/pair", status_code=201)
async def pair_channel(body: ChannelPairBody, user=Depends(get_current_user)):
    """Mint a single-use pairing code for the caller's tenant + agent +
    platform. Proxies agent-cloud POST /v1/agents/channels/pair."""
    tenant_id = _resolve_tenant(user, body.workspace)
    payload = {
        "tenant_id": tenant_id,  # server-side, always
        "agent_id": body.agent_id,
        "platform": body.platform,
    }
    return await _request_json(
        "POST", "/v1/agents/channels/pair", json_body=payload
    )


@router.get("/channels")
async def list_channels(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    workspace: Workspace = Workspace.personal,
    user=Depends(get_current_user),
):
    """List the caller's tenant's channel links. Proxies GET
    /v1/agents/channels."""
    tenant_id = _resolve_tenant(user, workspace)
    return await _get_json(
        "/v1/agents/channels",
        {"tenant_id": tenant_id, "limit": limit, "offset": offset},
    )


@router.post("/channels/{link_id}/revoke")
async def revoke_channel(
    link_id: uuid.UUID,
    workspace: Workspace = Workspace.personal,
    user=Depends(get_current_user),
):
    """Revoke a channel link. 404 for unknown/cross-tenant (indistinguishable).
    Proxies POST /v1/agents/channels/{link_id}/revoke."""
    tenant_id = _resolve_tenant(user, workspace)
    return await _request_json(
        "POST",
        f"/v1/agents/channels/{link_id}/revoke",
        params={"tenant_id": tenant_id},
    )


# ---------------------------------------------------------------------------
# Public channel webhook proxy (Phase D live-enablement).
#
# Telegram / Google Chat call these UNAUTHENTICATED (no Quill JWT). The api
# service is public; the orchestrator is IAM-locked. We forward the raw body
# and the platform's own auth header to the orchestrator's webhook, which does
# the real secret-token verification. No get_current_user dependency here on
# purpose — the platform secret token is the auth.
# ---------------------------------------------------------------------------
@router.post("/channels/{platform}/webhook")
async def public_channel_webhook(platform: str, request: Request):
    if platform not in ("telegram", "googlechat"):
        raise HTTPException(status_code=404, detail="unknown channel platform")
    raw = await request.body()
    # Preserve the platform verification header(s) verbatim.
    fwd_headers = {"content-type": request.headers.get("content-type", "application/json")}
    tg_secret = request.headers.get("x-telegram-bot-api-secret-token")
    if tg_secret is not None:
        fwd_headers["x-telegram-bot-api-secret-token"] = tg_secret
    gc_auth = request.headers.get("authorization")
    if gc_auth is not None:
        fwd_headers["authorization"] = gc_auth
    try:
        async with _client(timeout=30.0) as client:
            resp = await client.post(
                f"/v1/channels/{platform}/webhook",
                content=raw,
                headers=fwd_headers,
            )
    except httpx.HTTPError:
        # Never make the platform retry a poison delivery; ack.
        return JSONResponse({"ok": True, "ignored": "upstream unreachable"})
    # Pass the orchestrator's response through (Google Chat needs the body).
    try:
        return JSONResponse(resp.json(), status_code=resp.status_code)
    except Exception:  # noqa: BLE001
        return JSONResponse({"ok": True}, status_code=resp.status_code)
