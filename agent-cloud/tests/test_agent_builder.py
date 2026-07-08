"""Agent Builder CRUD (Phase C, AGENT_BUILDER.md): create/patch/soft-delete,
field validation, seed protection, cross-tenant isolation, catalog + templates,
and the agent.updated event. sqlite; no network."""

import httpx
import pytest

from app.api import app
from app import events as events_mod

TENANT = "smoke-tenant-builder"
OTHER = "smoke-tenant-builder-other"


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _create_body(agent_id="research", **over):
    body = {
        "tenant_id": TENANT,
        "agent_id": agent_id,
        "system_prompt": "You are a research assistant.",
        "model": "claude-fable-5",
        "tools": ["get_time", "quill_finance_summary"],
        "memory_policy": "off",
        "budget_monthly_usd": 5.0,
        "enabled": True,
    }
    body.update(over)
    return body


# --- catalog / templates -----------------------------------------------------


async def test_catalog_grouped_from_registry(client):
    async with client:
        r = await client.get("/v1/agents/catalog")
    assert r.status_code == 200
    body = r.json()
    groups = {g["group"]: g for g in body["groups"]}
    assert list(groups) == ["builtin", "read", "memory", "write"]
    # write group tools are all approval-gated
    assert all(t["approval_gated"] for t in groups["write"]["tools"])
    assert len(groups["write"]["tools"]) == 5
    assert len(groups["read"]["tools"]) == 6
    # memory tools flagged
    assert all(t["memory_tool"] for t in groups["memory"]["tools"])
    # builtin get_time is neither
    bt = groups["builtin"]["tools"][0]
    assert bt["name"] == "get_time" and not bt["approval_gated"]
    assert body["models"] == [
        "claude-fable-5",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ]
    assert body["memory_policies"] == ["off", "tools_only", "auto_recall"]


async def test_templates_three_starters(client):
    async with client:
        r = await client.get("/v1/agents/templates")
    assert r.status_code == 200
    tmpls = {t["template_id"]: t for t in r.json()["templates"]}
    assert set(tmpls) == {"research-assistant", "ops-analyst", "project-copilot"}
    # research is read-only, no writes/memory
    assert tmpls["research-assistant"]["memory_policy"] == "off"
    # project-copilot includes approval-gated writes
    assert "quill_project_update" in tmpls["project-copilot"]["tools"]
    assert tmpls["ops-analyst"]["memory_policy"] == "tools_only"


# --- create happy + validation ----------------------------------------------


async def test_create_agent_happy(client):
    async with client:
        r = await client.post("/v1/agents", json=_create_body())
    assert r.status_code == 201
    body = r.json()
    assert body["agent_id"] == "research"
    assert body["is_seed"] is False
    assert body["tools"] == ["get_time", "quill_finance_summary"]
    assert body["system_prompt"] == "You are a research assistant."


async def test_create_dedupes_tools(client):
    async with client:
        r = await client.post(
            "/v1/agents",
            json=_create_body(tools=["get_time", "get_time", "quill_finance_summary"]),
        )
    assert r.status_code == 201
    assert r.json()["tools"] == ["get_time", "quill_finance_summary"]


async def test_create_duplicate_409(client):
    async with client:
        await client.post("/v1/agents", json=_create_body())
        r = await client.post("/v1/agents", json=_create_body())
    assert r.status_code == 409


async def test_create_reserved_seed_id_409(client):
    async with client:
        # provision seeds first
        await client.get("/v1/agents", params={"tenant_id": TENANT})
        r = await client.post("/v1/agents", json=_create_body(agent_id="personal"))
    assert r.status_code == 409


@pytest.mark.parametrize(
    "field,value",
    [
        ("agent_id", "Bad_Slug"),
        ("agent_id", "-leading"),
        ("agent_id", "UPPER"),
        ("model", "gpt-4o"),
        ("memory_policy", "sometimes"),
        ("tools", ["get_time", "no_such_tool"]),
        ("system_prompt", "   "),
        ("budget_monthly_usd", 0),
        ("budget_monthly_usd", -5),
    ],
)
async def test_create_validation_400(client, field, value):
    async with client:
        r = await client.post("/v1/agents", json=_create_body(**{field: value}))
    assert r.status_code == 400, (field, value, r.text)


async def test_create_budget_over_tenant_cap_400(client):
    # smoke-* tenants get the org cap ($100); ask for more.
    async with client:
        r = await client.post(
            "/v1/agents", json=_create_body(budget_monthly_usd=100000)
        )
    assert r.status_code == 400
    assert "cap" in r.json()["detail"]


# --- read / patch / delete ---------------------------------------------------


async def test_get_agent_detail(client):
    async with client:
        await client.post("/v1/agents", json=_create_body())
        r = await client.get(
            "/v1/agents/research", params={"tenant_id": TENANT}
        )
    assert r.status_code == 200
    assert r.json()["agent_id"] == "research"
    assert "system_prompt" in r.json()


async def test_get_agent_unknown_404(client):
    async with client:
        r = await client.get("/v1/agents/nope", params={"tenant_id": TENANT})
    assert r.status_code == 404


async def test_patch_agent(client):
    async with client:
        await client.post("/v1/agents", json=_create_body())
        r = await client.patch(
            "/v1/agents/research",
            params={"tenant_id": TENANT},
            json={"system_prompt": "Updated.", "tools": ["get_time"], "enabled": False},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["system_prompt"] == "Updated."
    assert body["tools"] == ["get_time"]
    assert body["enabled"] is False


async def test_patch_validation_400(client):
    async with client:
        await client.post("/v1/agents", json=_create_body())
        r = await client.patch(
            "/v1/agents/research",
            params={"tenant_id": TENANT},
            json={"model": "not-a-model"},
        )
    assert r.status_code == 400


async def test_soft_delete(client):
    async with client:
        await client.post("/v1/agents", json=_create_body())
        r = await client.delete(
            "/v1/agents/research", params={"tenant_id": TENANT}
        )
        assert r.status_code == 200
        assert r.json() == {
            "agent_id": "research",
            "enabled": False,
            "soft_deleted": True,
        }
        # still readable (history preserved), just disabled
        d = await client.get("/v1/agents/research", params={"tenant_id": TENANT})
    assert d.status_code == 200
    assert d.json()["enabled"] is False


# --- seed protection (AGENT_BUILDER.md §3) -----------------------------------


async def test_seed_cannot_be_deleted(client):
    async with client:
        await client.get("/v1/agents", params={"tenant_id": TENANT})  # seed
        r = await client.delete(
            "/v1/agents/personal", params={"tenant_id": TENANT}
        )
    assert r.status_code == 403


async def test_seed_cannot_be_disabled(client):
    async with client:
        await client.get("/v1/agents", params={"tenant_id": TENANT})
        r = await client.patch(
            "/v1/agents/quill",
            params={"tenant_id": TENANT},
            json={"enabled": False},
        )
    assert r.status_code == 403


async def test_seed_can_be_tuned(client):
    async with client:
        await client.get("/v1/agents", params={"tenant_id": TENANT})
        r = await client.patch(
            "/v1/agents/personal",
            params={"tenant_id": TENANT},
            json={"system_prompt": "Tuned seed prompt.", "budget_monthly_usd": 3.0},
        )
    assert r.status_code == 200
    assert r.json()["system_prompt"] == "Tuned seed prompt."
    assert r.json()["is_seed"] is True


# --- cross-tenant isolation (404-not-403, TENANCY.md §4) ---------------------


async def test_cross_tenant_get_404(client):
    async with client:
        await client.post("/v1/agents", json=_create_body())  # in TENANT
        r = await client.get("/v1/agents/research", params={"tenant_id": OTHER})
    assert r.status_code == 404


async def test_cross_tenant_patch_404(client):
    async with client:
        await client.post("/v1/agents", json=_create_body())
        r = await client.patch(
            "/v1/agents/research",
            params={"tenant_id": OTHER},
            json={"system_prompt": "hijack"},
        )
    assert r.status_code == 404


async def test_cross_tenant_delete_404(client):
    async with client:
        await client.post("/v1/agents", json=_create_body())
        r = await client.delete("/v1/agents/research", params={"tenant_id": OTHER})
    assert r.status_code == 404


# --- events ------------------------------------------------------------------


async def test_agent_updated_event_on_create(client):
    async with client:
        await client.post("/v1/agents", json=_create_body())
    published = [e for e in events_mod.get_bus().published if e["type"] == "agent.updated"]
    assert len(published) == 1
    ev = published[0]
    assert ev["tenant_id"] == TENANT
    assert ev["agent_id"] == "research"
    assert ev["payload"] == {"action": "created", "fields": ["*"]}


async def test_agent_updated_event_on_delete(client):
    async with client:
        await client.post("/v1/agents", json=_create_body())
        await client.delete("/v1/agents/research", params={"tenant_id": TENANT})
    deletes = [
        e
        for e in events_mod.get_bus().published
        if e["type"] == "agent.updated" and e["payload"]["action"] == "deleted"
    ]
    assert len(deletes) == 1
    assert deletes[0]["payload"]["fields"] == ["enabled"]


# --- created agent is usable end-to-end via directory list -------------------


async def test_created_agent_appears_in_list(client):
    async with client:
        await client.post("/v1/agents", json=_create_body(agent_id="alpha"))
        r = await client.get("/v1/agents", params={"tenant_id": TENANT})
    ids = [a["agent_id"] for a in r.json()["items"]]
    assert "alpha" in ids
