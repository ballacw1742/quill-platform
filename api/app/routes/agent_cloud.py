"""Agent Cloud bridge routes — Sprint A5 (agent-cloud/WEBCHAT.md).

Authenticated Quill-web-facing endpoints that forward to the agent-cloud
orchestrator (quill-agent-orchestrator service). Same proxy conventions as
the /v1/sites DataSite proxy, with two hard rules from WEBCHAT.md:

  1. tenant_id is derived server-side (settings.AGENTCLOUD_TENANT_ID) —
     never read from the client. Any client-sent tenant_id is not even a
     schema field.
  2. Browser auth is the normal Quill JWT (get_current_user). No
     X-Agent-Secret ever reaches the browser; Quill API → agent-cloud is
     protected at the network/IAM layer like the DataSite proxy.

Endpoints (WEBCHAT.md §3):
  GET  /v1/agent-cloud/agents            — tenant agent directory
  GET  /v1/agent-cloud/sessions          — session list (optional agent_id)
  GET  /v1/agent-cloud/sessions/{id}     — full transcript
  POST /v1/agent-cloud/chat              — chat turn; stream=true ⇒ SSE
                                           passthrough, else JSON
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncIterator, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.security import get_current_user

log = logging.getLogger("quill.agent_cloud")

router = APIRouter(prefix="/v1/agent-cloud", tags=["agent-cloud"])

# Tests override this with an httpx.ASGITransport wired to a fake
# agent-cloud app; production leaves it None (real network transport).
TRANSPORT_OVERRIDE: Optional[httpx.AsyncBaseTransport] = None

_UNREACHABLE_DETAIL = "agent service unreachable"


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


# ---------------------------------------------------------------------------
# Reads (WEBCHAT.md §3.1–3.3)
# ---------------------------------------------------------------------------


@router.get("/agents")
async def list_agents(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user=Depends(get_current_user),
):
    settings = get_settings()
    return await _get_json(
        "/v1/agents",
        {"tenant_id": settings.AGENTCLOUD_TENANT_ID, "limit": limit, "offset": offset},
    )


@router.get("/sessions")
async def list_sessions(
    agent_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user=Depends(get_current_user),
):
    settings = get_settings()
    params: dict = {
        "tenant_id": settings.AGENTCLOUD_TENANT_ID,
        "limit": limit,
        "offset": offset,
    }
    if agent_id:
        params["agent_id"] = agent_id
    return await _get_json("/v1/agents/sessions", params)


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: uuid.UUID,
    user=Depends(get_current_user),
):
    settings = get_settings()
    return await _get_json(
        f"/v1/agents/sessions/{session_id}",
        {"tenant_id": settings.AGENTCLOUD_TENANT_ID},
    )


# ---------------------------------------------------------------------------
# Chat (WEBCHAT.md §3.4)
# ---------------------------------------------------------------------------


class AgentChatIn(BaseModel):
    """Client-facing chat body. Deliberately has NO tenant_id field — the
    tenant is a server-side constant (WEBCHAT.md §1)."""

    agent_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=8000)
    session_id: uuid.UUID | None = None
    stream: bool = False


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
    settings = get_settings()
    payload: dict = {
        "tenant_id": settings.AGENTCLOUD_TENANT_ID,  # server-side, always
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
