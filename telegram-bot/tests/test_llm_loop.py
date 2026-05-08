"""Tests for the ConversationalLLM tool-use loop (Phase B, Commit 4)."""

from __future__ import annotations

from typing import Any

import pytest

from quill_bot.config import BotConfig
from quill_bot.conversation import Message
from quill_bot.llm import ConversationalLLM, MAX_ITERATIONS
from quill_bot.tools import ChatContext, TOOL_REGISTRY


# ---------------------------------------------------------------------------
# Fake Anthropic client. Each call to messages.create() pops the next scripted
# response off a queue.
# ---------------------------------------------------------------------------
class _Block:
    def __init__(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


class _Usage:
    def __init__(
        self,
        input_tokens: int = 10,
        output_tokens: int = 20,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


class _Response:
    def __init__(self, *, stop_reason: str, content: list[Any], usage: _Usage | None = None):
        self.stop_reason = stop_reason
        self.content = content
        self.usage = usage or _Usage()


class _Messages:
    def __init__(self, scripted: list[_Response], record: list[dict[str, Any]]):
        self._scripted = scripted
        self._record = record

    def create(self, **kwargs: Any) -> _Response:
        self._record.append(kwargs)
        if not self._scripted:
            raise AssertionError("LLM called more times than scripted")
        return self._scripted.pop(0)


class FakeAnthropic:
    def __init__(self, scripted: list[_Response]) -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages = _Messages(scripted, self.calls)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class FakeAPIForLLM:
    """Tiny fake matching just what the tools we exercise will call."""

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "queue_depth_pending": 1, "audit_chain": "ok"}

    async def list_pending(self, *, lane=None, limit=10, offset=0):
        return [
            {
                "id": "ap-1",
                "lane": 2,
                "workflow": "rfi-triage",
                "agent_id": "rfi-triage",
                "status": "pending",
                "agent_confidence": 0.91,
                "payload": {"subject": "Chiller dunnage RFI"},
            }
        ]

    async def _req(self, method: str, path: str, *, admin=False, json=None, params=None):
        return []


@pytest.fixture
def ctx(bot_config: BotConfig) -> ChatContext:
    return ChatContext(api=FakeAPIForLLM(), config=bot_config, chat_id=1234567)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
async def test_two_tool_call_sequence_completes(ctx: ChatContext) -> None:
    """Iteration 1: tool_use(get_health). Iteration 2: tool_use(search_approvals).
    Iteration 3: end_turn with text."""
    scripted = [
        _Response(
            stop_reason="tool_use",
            content=[
                _Block(type="tool_use", id="tu-1", name="get_health", input={}),
            ],
        ),
        _Response(
            stop_reason="tool_use",
            content=[
                _Block(
                    type="tool_use",
                    id="tu-2",
                    name="search_approvals",
                    input={"limit": 5},
                ),
            ],
        ),
        _Response(
            stop_reason="end_turn",
            content=[
                _Block(type="text", text="The queue is healthy with 1 pending item."),
            ],
        ),
    ]
    fake = FakeAnthropic(scripted)
    llm = ConversationalLLM(fake)
    out = await llm.turn("How's the queue?", history=[], ctx=ctx)

    assert out.iterations == 3
    assert out.stop_reason == "end_turn"
    assert out.text == "The queue is healthy with 1 pending item."
    assert [tc.name for tc in out.tool_calls] == ["get_health", "search_approvals"]
    assert out.tool_calls[0].result["ok"] is True
    assert out.tool_calls[1].result["count"] == 1
    assert out.usage["input_tokens"] > 0


async def test_max_iterations_cap(ctx: ChatContext) -> None:
    """Loop returns even when Claude keeps calling tools."""
    scripted = [
        _Response(
            stop_reason="tool_use",
            content=[
                _Block(type="text", text=f"thinking-{i}"),
                _Block(type="tool_use", id=f"tu-{i}", name="get_health", input={}),
            ],
        )
        for i in range(MAX_ITERATIONS + 2)
    ]
    fake = FakeAnthropic(scripted)
    llm = ConversationalLLM(fake)
    out = await llm.turn("loop forever", history=[], ctx=ctx)
    assert out.iterations == MAX_ITERATIONS
    assert out.stop_reason == "max_iterations"
    assert out.text  # non-empty fallback


async def test_history_is_trimmed_before_call(ctx: ChatContext) -> None:
    """If history has 50 messages, only the most recent 24 are sent to Claude."""
    scripted = [
        _Response(
            stop_reason="end_turn",
            content=[_Block(type="text", text="ok")],
        ),
    ]
    fake = FakeAnthropic(scripted)
    llm = ConversationalLLM(fake)
    history = [
        Message(chat_id=1, role=("user" if i % 2 == 0 else "assistant"), content=f"m{i}")
        for i in range(50)
    ]
    await llm.turn("ping", history=history, ctx=ctx, max_history=10)

    sent = fake.calls[0]["messages"]
    # 10 trimmed history messages + 1 new user message = 11 total (or fewer
    # if the trimmer dropped one to start on a user-role boundary).
    assert 9 <= len(sent) <= 11
    # Last is the new user message
    assert sent[-1] == {"role": "user", "content": "ping"}
    # First message in history slice must be 'user' role.
    assert sent[0]["role"] == "user"


async def test_system_prompt_and_tools_have_cache_control(ctx: ChatContext) -> None:
    """Verify prompt-caching markers reach the API call."""
    scripted = [
        _Response(stop_reason="end_turn", content=[_Block(type="text", text="ok")]),
    ]
    fake = FakeAnthropic(scripted)
    llm = ConversationalLLM(fake)
    await llm.turn("hi", history=[], ctx=ctx)

    call = fake.calls[0]
    sys_blocks = call["system"]
    assert isinstance(sys_blocks, list)
    assert sys_blocks[0]["cache_control"] == {"type": "ephemeral"}
    # Last tool gets the cache marker.
    tools = call["tools"]
    assert tools[-1].get("cache_control") == {"type": "ephemeral"}


async def test_invalid_tool_input_recovers(ctx: ChatContext) -> None:
    """If Claude calls a tool with invalid input, the executor returns an
    error envelope and Claude can recover on the next turn."""
    scripted = [
        _Response(
            stop_reason="tool_use",
            content=[
                _Block(type="tool_use", id="tu-x", name="get_approval", input={}),
            ],
        ),
        _Response(
            stop_reason="end_turn",
            content=[_Block(type="text", text="That ID was missing — what's the ID?")],
        ),
    ]
    fake = FakeAnthropic(scripted)
    llm = ConversationalLLM(fake)
    out = await llm.turn("show me approval", history=[], ctx=ctx)
    assert out.stop_reason == "end_turn"
    assert "what's the id" in out.text.lower()
    assert out.tool_calls[0].result["error"] == "invalid_input"


async def test_default_model_is_sonnet_4_6() -> None:
    fake = FakeAnthropic([_Response(stop_reason="end_turn", content=[])])
    llm = ConversationalLLM(fake)
    assert llm.model == "claude-sonnet-4-6"


async def test_env_override_model(monkeypatch) -> None:
    monkeypatch.setenv("BOT_LLM_MODEL", "claude-haiku-4-5")
    fake = FakeAnthropic([_Response(stop_reason="end_turn", content=[])])
    llm = ConversationalLLM(fake)
    assert llm.model == "claude-haiku-4-5"


async def test_no_tool_calls_returns_text(ctx: ChatContext) -> None:
    scripted = [
        _Response(
            stop_reason="end_turn",
            content=[_Block(type="text", text="Good morning, Charles.")],
        ),
    ]
    fake = FakeAnthropic(scripted)
    llm = ConversationalLLM(fake)
    out = await llm.turn("hey", history=[], ctx=ctx)
    assert out.text == "Good morning, Charles."
    assert out.tool_calls == []
    assert out.iterations == 1


async def test_tool_registry_drives_tool_list() -> None:
    """The default tool list passed to Claude should contain all registered tools."""
    fake = FakeAnthropic([_Response(stop_reason="end_turn", content=[])])
    llm = ConversationalLLM(fake)
    names = {t["name"] for t in llm.tools}
    assert names == set(TOOL_REGISTRY.keys())


async def test_anthropic_error_surfaces_gracefully(ctx: ChatContext) -> None:
    class BoomMessages:
        def create(self, **kw):
            raise RuntimeError("api down")

    class BoomClient:
        messages = BoomMessages()

    llm = ConversationalLLM(BoomClient())
    out = await llm.turn("ping", history=[], ctx=ctx)
    assert out.stop_reason == "error"
    assert "error" in out.text.lower()
