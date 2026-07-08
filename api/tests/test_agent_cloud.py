"""Agent Cloud bridge tests — Sprint A5 (agent-cloud/WEBCHAT.md).

The agent-cloud service is mocked at the HTTP boundary with a fake ASGI app
mounted via httpx.ASGITransport (routes/agent_cloud.TRANSPORT_OVERRIDE).
Covers: auth required, server-side tenant derivation (client can never pick
a tenant), read passthrough shapes, SSE streaming proxy incl. the
budget-exceeded turn, and upstream error mapping.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from app.routes import agent_cloud as bridge
from tests.conftest import auth_h

# Since B1 (agent-cloud/TENANCY.md §1) the default tenant is per-user:
# "user-{user.id}". "quill-main" is reachable only via workspace=org
# (owner/partner) — covered in test_agentcloud_tenancy.py.
def expected_tenant(user_id: str) -> str:
    return f"user-{user_id}"

KNOWN_SESSION = "11111111-1111-1111-1111-111111111111"


def make_fake_agentcloud(calls: list) -> FastAPI:
    """Minimal fake of the agent-cloud API surface the bridge consumes."""
    fake = FastAPI()

    @fake.get("/v1/agents")
    async def list_agents(tenant_id: str, limit: int = 100, offset: int = 0):
        calls.append(("list_agents", tenant_id))
        return {
            "items": [
                {
                    "agent_id": "personal",
                    "model": "claude-haiku-4-5",
                    "enabled": True,
                    "memory_policy": "auto_recall",
                    "budget_monthly_usd": 20.0,
                    "created_at": "2026-07-07T12:00:00+00:00",
                },
                {
                    "agent_id": "quill",
                    "model": "claude-haiku-4-5",
                    "enabled": True,
                    "memory_policy": "off",
                    "budget_monthly_usd": 20.0,
                    "created_at": "2026-07-07T12:00:00+00:00",
                },
            ],
            "total": 2,
            "limit": limit,
            "offset": offset,
        }

    @fake.get("/v1/agents/usage")
    async def usage(tenant_id: str):
        calls.append(("usage", tenant_id))
        return {
            "month": "2026-07",
            "tenant": {
                "budget_monthly_usd": 10.0,
                "budget_source": "default",
                "spend_usd": 1.234567,
                "remaining_usd": 8.765433,
                "input_tokens": 12345,
                "output_tokens": 6789,
                "requests": 42,
                "exhausted": False,
            },
            "agents": [
                {
                    "agent_id": "personal",
                    "budget_monthly_usd": 20.0,
                    "spend_usd": 1.2,
                    "remaining_usd": 18.8,
                    "input_tokens": 12000,
                    "output_tokens": 6000,
                    "requests": 40,
                    "exhausted": False,
                }
            ],
        }

    @fake.get("/v1/agents/sessions")
    async def list_sessions(
        tenant_id: str, agent_id: str | None = None, limit: int = 50, offset: int = 0
    ):
        calls.append(("list_sessions", tenant_id, agent_id))
        return {
            "items": [
                {
                    "session_id": KNOWN_SESSION,
                    "agent_id": agent_id or "personal",
                    "preview": "remember the milk",
                    "created_at": "2026-07-07T12:00:00+00:00",
                    "updated_at": "2026-07-07T12:05:00+00:00",
                }
            ],
            "total": 1,
            "limit": limit,
            "offset": offset,
        }

    @fake.get("/v1/agents/sessions/{session_id}")
    async def transcript(session_id: uuid.UUID, tenant_id: str):
        calls.append(("transcript", tenant_id, str(session_id)))
        if str(session_id) != KNOWN_SESSION:
            raise HTTPException(404, "session not found for this tenant")
        return {
            "session_id": KNOWN_SESSION,
            "agent_id": "personal",
            "created_at": "2026-07-07T12:00:00+00:00",
            "updated_at": "2026-07-07T12:05:00+00:00",
            "messages": [
                {"role": "user", "content": "hi", "created_at": "2026-07-07T12:00:00+00:00"},
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "hello"}],
                    "created_at": "2026-07-07T12:00:01+00:00",
                },
            ],
        }

    @fake.post("/v1/agents/chat")
    async def chat(body: dict):
        calls.append(("chat", body.get("tenant_id"), body))
        if body.get("agent_id") == "ghost":
            raise HTTPException(404, "agent 'ghost' is not defined for this tenant")
        budget = body.get("message") == "trigger-budget"
        result = {
            "session_id": body.get("session_id") or KNOWN_SESSION,
            "reply": "You've hit the cap." if budget else "hello from fake agent-cloud",
            "tool_calls": [] if budget else ["get_time"],
            "model": "claude-haiku-4-5",
            "usage": {"input_tokens": 10, "output_tokens": 20, "cost_usd": 0.0003},
            "budget_exceeded": budget,
        }
        if not body.get("stream"):
            return result

        async def gen():
            yield f"event: session\ndata: {json.dumps({'session_id': result['session_id']})}\n\n"
            if not budget:
                yield 'event: tool\ndata: {"name": "get_time", "status": "start"}\n\n'
                yield 'event: tool\ndata: {"name": "get_time", "status": "ok"}\n\n'
            yield f"event: text\ndata: {json.dumps({'delta': result['reply']})}\n\n"
            yield f"event: done\ndata: {json.dumps(result)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    return fake


@pytest.fixture
def fake_agentcloud(monkeypatch):
    calls: list = []
    transport = httpx.ASGITransport(app=make_fake_agentcloud(calls))
    monkeypatch.setattr(bridge, "TRANSPORT_OVERRIDE", transport)
    return calls


# ─── auth ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/v1/agent-cloud/agents"),
        ("get", "/v1/agent-cloud/usage"),
        ("get", "/v1/agent-cloud/sessions"),
        ("get", f"/v1/agent-cloud/sessions/{KNOWN_SESSION}"),
        ("post", "/v1/agent-cloud/chat"),
    ],
)
async def test_all_routes_require_bearer(client, fake_agentcloud, method, path):
    kwargs = {"json": {"agent_id": "personal", "message": "hi"}} if method == "post" else {}
    r = await getattr(client, method)(path, **kwargs)
    assert r.status_code == 401
    assert fake_agentcloud == []  # never reached agent-cloud


# ─── tenant derivation ────────────────────────────────────────────────────────


async def test_tenant_injected_server_side(client, owner_token, fake_agentcloud):
    uid, token = owner_token
    r = await client.get("/v1/agent-cloud/agents", headers=auth_h(token))
    assert r.status_code == 200
    assert fake_agentcloud == [("list_agents", expected_tenant(uid))]


async def test_client_supplied_tenant_is_ignored(client, owner_token, fake_agentcloud):
    """A malicious tenant_id in the chat body must not reach agent-cloud."""
    uid, token = owner_token
    r = await client.post(
        "/v1/agent-cloud/chat",
        headers=auth_h(token),
        json={"agent_id": "personal", "message": "hi", "tenant_id": "victim-tenant"},
    )
    assert r.status_code == 200
    (_, forwarded_tenant, body) = fake_agentcloud[0]
    assert forwarded_tenant == expected_tenant(uid)
    assert body["tenant_id"] == expected_tenant(uid)


# ─── read passthrough shapes ──────────────────────────────────────────────────


async def test_usage_passthrough_and_tenant(client, owner_token, fake_agentcloud):
    uid, token = owner_token
    r = await client.get("/v1/agent-cloud/usage", headers=auth_h(token))
    assert r.status_code == 200
    assert fake_agentcloud == [("usage", expected_tenant(uid))]
    body = r.json()
    assert body["month"] == "2026-07"
    assert body["tenant"]["remaining_usd"] == 8.765433
    assert body["agents"][0]["agent_id"] == "personal"


async def test_list_agents_shape(client, owner_token, fake_agentcloud):
    _, token = owner_token
    r = await client.get("/v1/agent-cloud/agents", headers=auth_h(token))
    body = r.json()
    assert body["total"] == 2
    assert [a["agent_id"] for a in body["items"]] == ["personal", "quill"]
    assert body["items"][0]["memory_policy"] == "auto_recall"


async def test_list_sessions_forwards_agent_filter(client, owner_token, fake_agentcloud):
    uid, token = owner_token
    r = await client.get(
        "/v1/agent-cloud/sessions?agent_id=quill&limit=10", headers=auth_h(token)
    )
    assert r.status_code == 200
    assert fake_agentcloud == [("list_sessions", expected_tenant(uid), "quill")]
    item = r.json()["items"][0]
    assert set(item) == {"session_id", "agent_id", "preview", "created_at", "updated_at"}


async def test_transcript_passthrough_and_404(client, owner_token, fake_agentcloud):
    _, token = owner_token
    ok = await client.get(
        f"/v1/agent-cloud/sessions/{KNOWN_SESSION}", headers=auth_h(token)
    )
    assert ok.status_code == 200
    msgs = ok.json()["messages"]
    assert msgs[0]["content"] == "hi"
    assert msgs[1]["content"] == [{"type": "text", "text": "hello"}]

    missing = await client.get(
        f"/v1/agent-cloud/sessions/{uuid.uuid4()}", headers=auth_h(token)
    )
    assert missing.status_code == 404
    assert missing.json() == {"detail": "session not found for this tenant"}


# ─── chat: non-stream ─────────────────────────────────────────────────────────


async def test_chat_non_stream_passthrough(client, owner_token, fake_agentcloud):
    _, token = owner_token
    r = await client.post(
        "/v1/agent-cloud/chat",
        headers=auth_h(token),
        json={"agent_id": "personal", "message": "hi"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "hello from fake agent-cloud"
    assert body["budget_exceeded"] is False
    assert body["usage"]["cost_usd"] == 0.0003


async def test_chat_unknown_agent_404_envelope(client, owner_token, fake_agentcloud):
    _, token = owner_token
    r = await client.post(
        "/v1/agent-cloud/chat",
        headers=auth_h(token),
        json={"agent_id": "ghost", "message": "hi"},
    )
    assert r.status_code == 404
    assert "ghost" in r.json()["detail"]


async def test_chat_budget_exceeded_is_200_not_error(client, owner_token, fake_agentcloud):
    _, token = owner_token
    r = await client.post(
        "/v1/agent-cloud/chat",
        headers=auth_h(token),
        json={"agent_id": "personal", "message": "trigger-budget"},
    )
    assert r.status_code == 200
    assert r.json()["budget_exceeded"] is True


# ─── chat: SSE proxy ──────────────────────────────────────────────────────────


def _sse_events(text: str) -> list[tuple[str, dict]]:
    events = []
    current = None
    for line in text.splitlines():
        if line.startswith("event: "):
            current = line.removeprefix("event: ")
        elif line.startswith("data: ") and current:
            events.append((current, json.loads(line.removeprefix("data: "))))
    return events


async def test_chat_sse_passthrough(client, owner_token, fake_agentcloud):
    uid, token = owner_token
    text = ""
    async with client.stream(
        "POST",
        "/v1/agent-cloud/chat",
        headers=auth_h(token),
        json={"agent_id": "personal", "message": "hi", "stream": True},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        async for chunk in resp.aiter_text():
            text += chunk
    events = _sse_events(text)
    names = [e[0] for e in events]
    assert names == ["session", "tool", "tool", "text", "done"]
    done = dict(events)["done"]
    assert done["reply"] == "hello from fake agent-cloud"
    assert done["budget_exceeded"] is False
    # tenant went in server-side
    assert fake_agentcloud[0][1] == expected_tenant(uid)


async def test_chat_sse_budget_exceeded_flows_as_done(client, owner_token, fake_agentcloud):
    _, token = owner_token
    text = ""
    async with client.stream(
        "POST",
        "/v1/agent-cloud/chat",
        headers=auth_h(token),
        json={"agent_id": "personal", "message": "trigger-budget", "stream": True},
    ) as resp:
        assert resp.status_code == 200
        async for chunk in resp.aiter_text():
            text += chunk
    events = dict(_sse_events(text))
    assert events["done"]["budget_exceeded"] is True


async def test_chat_sse_upstream_4xx_becomes_error_event(client, owner_token, fake_agentcloud):
    _, token = owner_token
    text = ""
    async with client.stream(
        "POST",
        "/v1/agent-cloud/chat",
        headers=auth_h(token),
        json={"agent_id": "ghost", "message": "hi", "stream": True},
    ) as resp:
        assert resp.status_code == 200  # stream already started; error is an event
        async for chunk in resp.aiter_text():
            text += chunk
    events = _sse_events(text)
    assert events[0][0] == "error"
    assert events[0][1]["status"] == 404


# ─── unreachable upstream ─────────────────────────────────────────────────────


class _ExplodingTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):  # noqa: D102
        raise httpx.ConnectError("boom", request=request)


async def test_unreachable_agent_cloud_502(client, owner_token, monkeypatch):
    _, token = owner_token
    monkeypatch.setattr(bridge, "TRANSPORT_OVERRIDE", _ExplodingTransport())
    r = await client.get("/v1/agent-cloud/agents", headers=auth_h(token))
    assert r.status_code == 502
    assert r.json() == {"detail": "agent service unreachable"}


async def test_unreachable_agent_cloud_sse_error_event(client, owner_token, monkeypatch):
    _, token = owner_token
    monkeypatch.setattr(bridge, "TRANSPORT_OVERRIDE", _ExplodingTransport())
    text = ""
    async with client.stream(
        "POST",
        "/v1/agent-cloud/chat",
        headers=auth_h(token),
        json={"agent_id": "personal", "message": "hi", "stream": True},
    ) as resp:
        async for chunk in resp.aiter_text():
            text += chunk
    events = _sse_events(text)
    assert events == [("error", {"detail": "agent service unreachable", "status": 502})]
