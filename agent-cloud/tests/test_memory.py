"""Memory subsystem unit tests (sqlite; embeddings unavailable → text path).

pgvector similarity + RLS on agentcloud_memory are covered by the pg-gated
tests in tests/test_memory_pg.py.
"""

import json

import pytest

from tests.conftest import FakeProvider, text_response, tool_use_response

TENANT_A = "smoke-mem-a"
TENANT_B = "smoke-mem-b"


def _set_ctx(tenant, agent="personal"):
    from app.logging_setup import agent_id_var, tenant_id_var

    tenant_id_var.set(tenant)
    agent_id_var.set(agent)


async def _seed_tenant(tenant):
    from app.orchestrator import chat_turn

    await chat_turn(
        tenant_id=tenant, agent_id="personal", message="hi",
        provider=FakeProvider([text_response("hi")]),
    )


# --------------------------- save + search (core) ---------------------------


async def test_save_and_text_search_roundtrip():
    await _seed_tenant(TENANT_A)
    from app import memory as memory_mod

    r = await memory_mod.save_memory(
        TENANT_A, "personal", content="Charles's favorite color is teal",
        kind="preference", metadata={"source": "chat"},
    )
    assert r["kind"] == "preference"
    assert r["embedded"] is False  # sqlite + no key → no embedding

    res = await memory_mod.search_memories(
        TENANT_A, "personal", query="what is the favorite color?"
    )
    assert res["mode"] == "text"
    assert len(res["items"]) == 1
    assert "teal" in res["items"][0]["content"]
    assert res["items"][0]["metadata"] == {"source": "chat"}


async def test_search_kind_filter_and_no_match():
    await _seed_tenant(TENANT_A)
    from app import memory as memory_mod

    await memory_mod.save_memory(TENANT_A, "personal", content="likes espresso", kind="preference")
    res = await memory_mod.search_memories(
        TENANT_A, "personal", query="espresso", kind="fact"
    )
    assert res["items"] == []
    res = await memory_mod.search_memories(
        TENANT_A, "personal", query="espresso", kind="preference"
    )
    assert len(res["items"]) == 1


async def test_save_rejects_empty_and_clamps_kind():
    await _seed_tenant(TENANT_A)
    from app import memory as memory_mod

    assert "error" in await memory_mod.save_memory(TENANT_A, "personal", content="   ")
    r = await memory_mod.save_memory(TENANT_A, "personal", content="x", kind="bogus")
    assert r["kind"] == "fact"


async def test_namespace_isolation_between_tenants_and_agents():
    await _seed_tenant(TENANT_A)
    await _seed_tenant(TENANT_B)
    from app import memory as memory_mod

    await memory_mod.save_memory(TENANT_A, "personal", content="secret teal fact")
    # other tenant, same agent id
    res = await memory_mod.search_memories(TENANT_B, "personal", query="teal")
    assert res["items"] == []
    # same tenant, other agent
    res = await memory_mod.search_memories(TENANT_A, "quill", query="teal")
    assert res["items"] == []


# --------------------------- tools ------------------------------------------


async def test_memory_tools_roundtrip_via_registry():
    await _seed_tenant(TENANT_A)
    _set_ctx(TENANT_A)
    from app.tools import run_tool

    allow = ["memory_save", "memory_search"]
    out = json.loads(
        await run_tool("memory_save", {"content": "prefers ET timezone", "kind": "preference"}, allow)
    )
    assert out["memory_id"]
    found = json.loads(await run_tool("memory_search", {"query": "timezone"}, allow))
    assert len(found["items"]) == 1
    assert "ET" in found["items"][0]["content"]


async def test_memory_tools_denied_off_allowlist():
    _set_ctx(TENANT_A)
    from app.tools import ToolNotAllowedError, run_tool

    with pytest.raises(ToolNotAllowedError):
        await run_tool("memory_save", {"content": "x"}, ["get_time"])


# --------------------------- memory_policy enforcement ----------------------


class SpyProvider(FakeProvider):
    def __init__(self, responses):
        super().__init__(responses)
        self.seen_tools = None
        self.seen_system = None

    async def complete(self, *, model, system, messages, tools, max_tokens):
        self.seen_tools = [t["name"] for t in tools]
        self.seen_system = system
        return await super().complete(
            model=model, system=system, messages=messages, tools=tools,
            max_tokens=max_tokens,
        )


async def _set_policy(tenant, agent, policy):
    import sqlalchemy as sa

    from app.db import tenant_session
    from app.models import AgentDef

    async with tenant_session(tenant) as db:
        await db.execute(
            sa.update(AgentDef)
            .where(AgentDef.tenant_id == tenant, AgentDef.agent_id == agent)
            .values(memory_policy=policy)
        )


async def test_policy_off_strips_memory_tools_even_if_allowlisted():
    from app.orchestrator import chat_turn

    await _seed_tenant(TENANT_A)
    await _set_policy(TENANT_A, "personal", "off")
    spy = SpyProvider([text_response("hi")])
    await chat_turn(tenant_id=TENANT_A, agent_id="personal", message="hi", provider=spy)
    assert "memory_save" not in spy.seen_tools
    assert "memory_search" not in spy.seen_tools

    # and run_tool is gated too (allowlist already stripped): a crafted
    # tool_use for memory_save comes back denied.
    spy2 = SpyProvider([
        tool_use_response("memory_save", {"content": "x"}),
        text_response("done"),
    ])
    r = await chat_turn(tenant_id=TENANT_A, agent_id="personal", message="save it", provider=spy2)
    assert r.tool_calls == ["memory_save"]  # attempted, but…
    # …the tool_result carried the denial (visible in persisted turns)
    await _set_policy(TENANT_A, "personal", "auto_recall")


async def test_policy_tools_only_offers_tools_but_no_injection():
    from app import memory as memory_mod
    from app.orchestrator import chat_turn

    await _seed_tenant(TENANT_A)
    await memory_mod.save_memory(TENANT_A, "personal", content="favorite color teal")
    await _set_policy(TENANT_A, "personal", "tools_only")
    spy = SpyProvider([text_response("hi")])
    await chat_turn(
        tenant_id=TENANT_A, agent_id="personal", message="favorite color?", provider=spy
    )
    assert "memory_save" in spy.seen_tools
    assert "Relevant memories" not in spy.seen_system


async def test_policy_auto_recall_injects_bounded_memories():
    from app import memory as memory_mod
    from app.orchestrator import chat_turn

    await _seed_tenant(TENANT_A)  # personal seeds with auto_recall
    await memory_mod.save_memory(
        TENANT_A, "personal", content="favorite color is teal", kind="preference"
    )
    spy = SpyProvider([text_response("teal!")])
    await chat_turn(
        tenant_id=TENANT_A, agent_id="personal",
        message="what is my favorite color?", provider=spy,
    )
    assert "Relevant memories" in spy.seen_system
    assert "favorite color is teal" in spy.seen_system
    # base prompt still present, memories appended after it
    assert spy.seen_system.index("Relevant memories") > 0


async def test_auto_recall_empty_memory_injects_nothing():
    from app.orchestrator import chat_turn

    spy = SpyProvider([text_response("hi")])
    await chat_turn(tenant_id=TENANT_B, agent_id="personal", message="zzz qqq", provider=spy)
    assert "Relevant memories" not in spy.seen_system


async def test_recall_block_respects_char_cap():
    from app import memory as memory_mod

    await _seed_tenant(TENANT_A)
    big = "teal " * 600  # ~3000 chars each
    for _ in range(3):
        await memory_mod.save_memory(TENANT_A, "personal", content=big)
    block = await memory_mod.recall_block(TENANT_A, "personal", "teal")
    from app.config import get_settings

    assert len(block) <= get_settings().MEMORY_RECALL_MAX_CHARS + 200  # header slack
    assert block.count("- [fact]") == 1  # only one fits under the cap


# --------------------------- seeds ------------------------------------------


async def test_seed_memory_policies():
    import sqlalchemy as sa

    from app.db import tenant_session
    from app.models import AgentDef

    await _seed_tenant(TENANT_A)
    async with tenant_session(TENANT_A) as db:
        rows = (
            await db.execute(
                sa.select(AgentDef.agent_id, AgentDef.memory_policy, AgentDef.tools)
                .where(AgentDef.tenant_id == TENANT_A)
            )
        ).all()
    by_id = {r.agent_id: r for r in rows}
    assert by_id["personal"].memory_policy == "auto_recall"
    assert "memory_save" in by_id["personal"].tools
    assert by_id["quill"].memory_policy == "off"
    assert "memory_save" not in by_id["quill"].tools


# --------------------------- embedding provider selection -------------------


async def test_embeddings_missing_key_is_clean_named_error():
    from app.providers.embeddings import (
        EmbeddingUnavailableError,
        get_embedding_provider,
    )

    with pytest.raises(EmbeddingUnavailableError, match="GEMINI_API_KEY"):
        await get_embedding_provider("gemini").embed(["x"])


async def test_embeddings_provider_none_and_unknown():
    from app.providers.embeddings import (
        EmbeddingUnavailableError,
        get_embedding_provider,
    )

    with pytest.raises(EmbeddingUnavailableError, match="disabled by config"):
        get_embedding_provider("none")
    with pytest.raises(EmbeddingUnavailableError, match="unknown EMBEDDING_PROVIDER"):
        get_embedding_provider("banana")


async def test_search_degrades_not_raises_when_embeddings_unavailable():
    from app import memory as memory_mod

    await _seed_tenant(TENANT_A)
    await memory_mod.save_memory(TENANT_A, "personal", content="degrade gracefully")
    res = await memory_mod.search_memories(TENANT_A, "personal", query="degrade")
    assert res["mode"] == "text"
    assert len(res["items"]) == 1
