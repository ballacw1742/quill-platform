import httpx
import pytest

import app.orchestrator as orch_mod
from app.api import app
from tests.conftest import FakeProvider, text_response, tool_use_response

TENANT = "smoke-tenant-api"


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def patch_provider(monkeypatch):
    def _patch(responses):
        provider = FakeProvider(responses)
        monkeypatch.setattr(orch_mod, "get_provider", lambda *a, **k: provider)
        return provider

    return _patch


async def test_health_200(client):
    async with client:
        r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["db"] == "up"
    assert "X-Request-Id" in r.headers


async def test_chat_non_streaming(client, patch_provider):
    patch_provider([text_response("hello from the platform core")])
    async with client:
        r = await client.post(
            "/v1/agents/chat",
            json={"tenant_id": TENANT, "agent_id": "personal", "message": "hi"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "hello from the platform core"
    assert body["budget_exceeded"] is False
    assert body["usage"]["input_tokens"] == 10
    assert body["usage"]["cost_usd"] > 0


async def test_chat_unknown_agent_404(client, patch_provider):
    patch_provider([text_response("x")])
    async with client:
        r = await client.post(
            "/v1/agents/chat",
            json={"tenant_id": TENANT, "agent_id": "ghost", "message": "hi"},
        )
    assert r.status_code == 404
    assert "detail" in r.json()


async def test_chat_cross_tenant_session_404(client, patch_provider):
    patch_provider([text_response("a"), text_response("b")])
    async with client:
        r1 = await client.post(
            "/v1/agents/chat",
            json={"tenant_id": TENANT, "agent_id": "personal", "message": "hi"},
        )
        sid = r1.json()["session_id"]
        r2 = await client.post(
            "/v1/agents/chat",
            json={
                "tenant_id": "smoke-tenant-other",
                "agent_id": "personal",
                "message": "steal",
                "session_id": sid,
            },
        )
    assert r1.status_code == 200
    assert r2.status_code == 404


async def test_chat_sse_stream_includes_tool_status_events(client, patch_provider):
    patch_provider(
        [tool_use_response("get_time"), text_response("the time is now")]
    )
    events = []
    async with client:
        async with client.stream(
            "POST",
            "/v1/agents/chat",
            json={
                "tenant_id": TENANT,
                "agent_id": "personal",
                "message": "time?",
                "stream": True,
            },
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            text = ""
            async for chunk in resp.aiter_text():
                text += chunk
    for line in text.splitlines():
        if line.startswith("event: "):
            events.append(line.removeprefix("event: "))
    assert "session" in events
    assert "tool" in events  # tool-call status events present
    assert "done" in events
    assert events.count("tool") == 2  # start + ok
    assert '"status": "start"' in text
    assert '"status": "ok"' in text


async def test_chat_sse_error_event_for_unknown_agent(client, patch_provider):
    patch_provider([text_response("x")])
    async with client:
        async with client.stream(
            "POST",
            "/v1/agents/chat",
            json={
                "tenant_id": TENANT,
                "agent_id": "ghost",
                "message": "hi",
                "stream": True,
            },
        ) as resp:
            text = ""
            async for chunk in resp.aiter_text():
                text += chunk
    assert "event: error" in text
    assert '"status": 404' in text
