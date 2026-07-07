"""A5 web-chat read endpoints (WEBCHAT.md §5): agents list, sessions list,
session transcript. sqlite; provider faked like tests/test_api.py."""

import httpx
import pytest

import app.orchestrator as orch_mod
from app.api import app
from tests.conftest import FakeProvider, text_response, tool_use_response

TENANT = "smoke-tenant-directory"
OTHER = "smoke-tenant-directory-other"


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


# --- GET /v1/agents ---------------------------------------------------------


async def test_list_agents_seeds_fresh_tenant(client):
    """A fresh tenant sees personal + quill from the list endpoint alone."""
    async with client:
        r = await client.get("/v1/agents", params={"tenant_id": TENANT})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    ids = [a["agent_id"] for a in body["items"]]
    assert ids == ["personal", "quill"]  # ordered by agent_id
    personal = body["items"][0]
    # WEBCHAT.md §3.1 field set
    assert set(personal) == {
        "agent_id", "model", "enabled", "memory_policy",
        "budget_monthly_usd", "created_at",
    }
    assert personal["enabled"] is True
    assert personal["memory_policy"] == "auto_recall"
    # smoke- prefix seeds the cheap tier
    assert personal["model"] == "claude-haiku-4-5"


async def test_list_agents_idempotent_and_envelope(client):
    async with client:
        r1 = await client.get("/v1/agents", params={"tenant_id": TENANT})
        r2 = await client.get("/v1/agents", params={"tenant_id": TENANT})
    assert r1.json()["total"] == r2.json()["total"] == 2
    for key in ("items", "total", "limit", "offset"):
        assert key in r2.json()


# --- GET /v1/agents/sessions -------------------------------------------------


async def test_sessions_list_scoped_with_preview(client, patch_provider):
    patch_provider([text_response("hi"), text_response("yo"), text_response("z")])
    async with client:
        r1 = await client.post(
            "/v1/agents/chat",
            json={"tenant_id": TENANT, "agent_id": "personal",
                  "message": "remember the milk and other things beyond"},
        )
        r2 = await client.post(
            "/v1/agents/chat",
            json={"tenant_id": TENANT, "agent_id": "quill", "message": "arr?"},
        )
        # other tenant's session must never appear
        await client.post(
            "/v1/agents/chat",
            json={"tenant_id": OTHER, "agent_id": "personal", "message": "secret"},
        )
        r = await client.get("/v1/agents/sessions", params={"tenant_id": TENANT})
        rf = await client.get(
            "/v1/agents/sessions",
            params={"tenant_id": TENANT, "agent_id": "personal"},
        )
    assert r1.status_code == r2.status_code == 200
    body = r.json()
    assert body["total"] == 2
    sids = {s["session_id"] for s in body["items"]}
    assert sids == {r1.json()["session_id"], r2.json()["session_id"]}
    by_id = {s["session_id"]: s for s in body["items"]}
    assert by_id[r1.json()["session_id"]]["preview"].startswith("remember the milk")
    assert by_id[r1.json()["session_id"]]["agent_id"] == "personal"
    # agent_id filter
    fbody = rf.json()
    assert fbody["total"] == 1
    assert fbody["items"][0]["agent_id"] == "personal"


async def test_sessions_list_empty_tenant_ok(client):
    async with client:
        r = await client.get(
            "/v1/agents/sessions", params={"tenant_id": "smoke-tenant-nobody"}
        )
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


# --- GET /v1/agents/sessions/{id} --------------------------------------------


async def test_transcript_roundtrip_with_tool_blocks(client, patch_provider):
    patch_provider([tool_use_response("get_time"), text_response("it is now")])
    async with client:
        r1 = await client.post(
            "/v1/agents/chat",
            json={"tenant_id": TENANT, "agent_id": "personal", "message": "time?"},
        )
        sid = r1.json()["session_id"]
        r = await client.get(
            f"/v1/agents/sessions/{sid}", params={"tenant_id": TENANT}
        )
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == sid
    assert body["agent_id"] == "personal"
    msgs = body["messages"]
    # user str, assistant tool_use blocks, user tool_result blocks, assistant text
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[0]["content"] == "time?"
    assert any(
        b.get("type") == "tool_use" and b.get("name") == "get_time"
        for b in msgs[1]["content"]
    )
    assert msgs[2]["content"][0]["type"] == "tool_result"
    assert msgs[3]["content"] == [{"type": "text", "text": "it is now"}]
    for m in msgs:
        assert "created_at" in m


async def test_transcript_cross_tenant_404(client, patch_provider):
    patch_provider([text_response("a")])
    async with client:
        r1 = await client.post(
            "/v1/agents/chat",
            json={"tenant_id": TENANT, "agent_id": "personal", "message": "hi"},
        )
        sid = r1.json()["session_id"]
        r = await client.get(
            f"/v1/agents/sessions/{sid}", params={"tenant_id": OTHER}
        )
    assert r.status_code == 404
    assert "detail" in r.json()


async def test_transcript_unknown_404(client):
    async with client:
        r = await client.get(
            "/v1/agents/sessions/00000000-0000-0000-0000-000000000000",
            params={"tenant_id": TENANT},
        )
    assert r.status_code == 404
