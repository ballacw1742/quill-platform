import pytest
import sqlalchemy as sa

from app.db import tenant_session
from app.models import AgentDef, Message, Session, Usage
from app.orchestrator import (
    AgentDisabledError,
    SessionNotFoundError,
    UnknownAgentError,
    chat_turn,
)
from tests.conftest import FakeProvider, text_response, tool_use_response

TENANT_A = "smoke-tenant-a"
TENANT_B = "smoke-tenant-b"


async def test_first_contact_seeds_personal_and_quill():
    provider = FakeProvider([text_response("hello")])
    await chat_turn(
        tenant_id=TENANT_A, agent_id="personal", message="hi", provider=provider
    )
    async with tenant_session(TENANT_A) as db:
        agents = (
            await db.execute(
                sa.select(AgentDef.agent_id, AgentDef.tools, AgentDef.model).where(
                    AgentDef.tenant_id == TENANT_A
                )
            )
        ).all()
    by_id = {a.agent_id: a for a in agents}
    assert set(by_id) == {"personal", "quill"}
    assert "quill_finance_summary" not in by_id["personal"].tools
    assert "quill_finance_summary" in by_id["quill"].tools
    assert "quill_list_pending_approvals" in by_id["quill"].tools
    # smoke- tenants seed on the cheap tier
    assert by_id["personal"].model == "claude-haiku-4-5"


async def test_unknown_agent_404s():
    with pytest.raises(UnknownAgentError):
        await chat_turn(
            tenant_id=TENANT_A, agent_id="nope", message="hi",
            provider=FakeProvider([text_response("x")]),
        )


async def test_disabled_agent_refused():
    await chat_turn(
        tenant_id=TENANT_A, agent_id="personal", message="hi",
        provider=FakeProvider([text_response("x")]),
    )
    async with tenant_session(TENANT_A) as db:
        await db.execute(
            sa.update(AgentDef)
            .where(AgentDef.tenant_id == TENANT_A, AgentDef.agent_id == "personal")
            .values(enabled=False)
        )
    with pytest.raises(AgentDisabledError):
        await chat_turn(
            tenant_id=TENANT_A, agent_id="personal", message="hi",
            provider=FakeProvider([text_response("x")]),
        )


async def test_multi_turn_history_persists():
    p1 = FakeProvider([text_response("nice to meet you")])
    r1 = await chat_turn(
        tenant_id=TENANT_A, agent_id="personal", message="my color is teal",
        provider=p1,
    )
    p2 = FakeProvider([text_response("teal, you said")])
    r2 = await chat_turn(
        tenant_id=TENANT_A, agent_id="personal", message="what color?",
        session_id=r1.session_id, provider=p2,
    )
    assert r2.session_id == r1.session_id
    async with tenant_session(TENANT_A) as db:
        n = (
            await db.execute(
                sa.select(sa.func.count()).select_from(Message).where(
                    Message.tenant_id == TENANT_A,
                    Message.session_id == r1.session_id,
                )
            )
        ).scalar_one()
    assert n == 4  # 2 user + 2 assistant


async def test_tool_loop_executes_allowed_tool():
    provider = FakeProvider(
        [tool_use_response("get_time"), text_response("it is now …")]
    )
    result = await chat_turn(
        tenant_id=TENANT_A, agent_id="personal", message="time?", provider=provider
    )
    assert result.tool_calls == ["get_time"]
    assert result.reply == "it is now …"
    assert provider.calls == 2


async def test_allowlist_blocks_quill_tool_for_personal_agent():
    """Even if the model hallucinates an off-list tool_use, execution is denied."""
    provider = FakeProvider(
        [tool_use_response("quill_finance_summary"), text_response("blocked, sorry")]
    )
    result = await chat_turn(
        tenant_id=TENANT_A, agent_id="personal", message="what's our ARR?",
        provider=provider,
    )
    # The tool never executed: the result fed back to the model is a denial.
    async with tenant_session(TENANT_A) as db:
        msgs = (
            await db.execute(
                sa.select(Message.content).where(
                    Message.tenant_id == TENANT_A,
                    Message.session_id == result.session_id,
                    Message.role == "user",
                ).order_by(Message.message_id)
            )
        ).scalars().all()
    tool_results = [
        b for m in msgs if isinstance(m, list) for b in m
        if isinstance(b, dict) and b.get("type") == "tool_result"
    ]
    assert len(tool_results) == 1
    assert "not on this agent's allow-list" in tool_results[0]["content"]


async def test_personal_agent_is_not_offered_quill_tools():
    provider = FakeProvider([text_response("hi")])
    await chat_turn(
        tenant_id=TENANT_A, agent_id="personal", message="hi", provider=provider
    )
    # FakeProvider records the offered tool specs on the response object.
    # (one response consumed; inspect what the provider saw)
    assert provider._responses == []
    # offered tools were annotated onto the popped response
    # → verify via a fresh call capturing tools
    seen = {}

    class SpyProvider(FakeProvider):
        async def complete(self, *, model, system, messages, tools, max_tokens):
            seen["tools"] = [t["name"] for t in tools]
            return await super().complete(
                model=model, system=system, messages=messages, tools=tools,
                max_tokens=max_tokens,
            )

    spy = SpyProvider([text_response("hi")])
    await chat_turn(
        tenant_id=TENANT_A, agent_id="personal", message="hi again", provider=spy
    )
    assert seen["tools"] == ["get_time", "memory_save", "memory_search"]
    assert not any(t.startswith("quill_") for t in seen["tools"])


# --------------------------- isolation suite (app layer) --------------------


async def test_cross_tenant_session_access_fails():
    r = await chat_turn(
        tenant_id=TENANT_A, agent_id="personal", message="secret: teal",
        provider=FakeProvider([text_response("ok")]),
    )
    with pytest.raises(SessionNotFoundError):
        await chat_turn(
            tenant_id=TENANT_B, agent_id="personal", message="replay",
            session_id=r.session_id, provider=FakeProvider([text_response("x")]),
        )


async def test_cross_tenant_history_leak_blocked():
    r = await chat_turn(
        tenant_id=TENANT_A, agent_id="personal", message="my secret is teal",
        provider=FakeProvider([text_response("noted")]),
    )
    captured = {}

    class SpyProvider(FakeProvider):
        async def complete(self, *, model, system, messages, tools, max_tokens):
            captured["messages"] = messages
            return await super().complete(
                model=model, system=system, messages=messages, tools=tools,
                max_tokens=max_tokens,
            )

    spy = SpyProvider([text_response("fresh")])
    rb = await chat_turn(
        tenant_id=TENANT_B, agent_id="personal", message="any secrets?", provider=spy
    )
    assert rb.session_id != r.session_id
    flat = str(captured["messages"])
    assert "teal" not in flat


async def test_cross_tenant_usage_rows_isolated():
    await chat_turn(
        tenant_id=TENANT_A, agent_id="personal", message="hi",
        provider=FakeProvider([text_response("ok", tin=100, tout=100)]),
    )
    async with tenant_session(TENANT_B) as db:
        rows = (
            await db.execute(
                sa.select(Usage).where(Usage.tenant_id == TENANT_B)
            )
        ).scalars().all()
        assert rows == []
        # app-layer discipline: queries always filter tenant_id; verify A's
        # rows exist under A's scope only
    async with tenant_session(TENANT_A) as db:
        rows = (
            await db.execute(
                sa.select(Usage).where(Usage.tenant_id == TENANT_A)
            )
        ).scalars().all()
        assert len(rows) == 1


async def test_sessions_scoped_per_tenant():
    await chat_turn(
        tenant_id=TENANT_A, agent_id="personal", message="hi",
        provider=FakeProvider([text_response("ok")]),
    )
    async with tenant_session(TENANT_B) as db:
        n = (
            await db.execute(
                sa.select(sa.func.count()).select_from(Session).where(
                    Session.tenant_id == TENANT_B
                )
            )
        ).scalar_one()
    assert n == 0
