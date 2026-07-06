"""Test env must be pinned BEFORE any app import (settings are lru_cached)."""

import os
import pathlib
import sys

_TEST_DB = "/tmp/agentcloud_pytest.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB}"
os.environ["ANTHROPIC_API_KEY"] = "test-not-a-real-key"
os.environ["MODEL_PROVIDER"] = "anthropic"
os.environ["MODEL_DEFAULT"] = "claude-fable-5"
os.environ["MODEL_CHEAP"] = "claude-haiku-4-5"
os.environ["QUILL_AGENT_SECRET"] = ""  # quill tools short-circuit, no network
os.environ["DEFAULT_BUDGET_MONTHLY_USD"] = "20"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.db import Base, engine  # noqa: E402
import app.models  # noqa: F401, E402


@pytest.fixture(autouse=True)
async def _fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


class FakeProvider:
    """Scripted ModelProvider (duck-typed; base-class stream fallback copied)."""

    name = "fake"

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def complete(self, *, model, system, messages, tools, max_tokens):
        self.calls += 1
        resp = self._responses.pop(0)
        # annotate which tools the model was offered (for allow-list asserts)
        resp.meta_offered_tools = [t["name"] for t in tools]
        return resp

    def stream(self, *, model, system, messages, tools, max_tokens):
        from app.providers.base import StreamEvent

        async def _gen():
            resp = await self.complete(
                model=model, system=system, messages=messages, tools=tools,
                max_tokens=max_tokens,
            )
            if resp.text:
                yield StreamEvent(type="text_delta", text=resp.text)
            yield StreamEvent(type="final", response=resp)

        return _gen()


def text_response(text: str, model: str = "claude-haiku-4-5", tin: int = 10, tout: int = 20):
    from app.providers.base import ModelResponse

    return ModelResponse(
        content=[{"type": "text", "text": text}],
        stop_reason="end_turn",
        model=model,
        input_tokens=tin,
        output_tokens=tout,
    )


def tool_use_response(tool_name: str, args: dict | None = None, model: str = "claude-haiku-4-5"):
    from app.providers.base import ModelResponse

    return ModelResponse(
        content=[
            {"type": "text", "text": f"Let me check {tool_name}."},
            {"type": "tool_use", "id": "toolu_test_1", "name": tool_name, "input": args or {}},
        ],
        stop_reason="tool_use",
        model=model,
        input_tokens=15,
        output_tokens=25,
    )


@pytest.fixture
def fake_provider_factory():
    return FakeProvider
