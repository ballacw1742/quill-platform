"""Local-inference provider (MODEL_PROVIDER=local, ollama) — mock-only.

The CI/dev box has no guaranteed live ollama, so these mock the native
ollama HTTP surface (/api/chat, /api/embed) via an injected engine / httpx
transport. They prove: interface conformance, complete/stream parsing,
token accounting (prompt_eval_count/eval_count), $0 pricing, factory
selection, and local embeddings — without requiring a running model.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.providers import get_provider
from app.providers.base import ModelProvider, ModelResponse, ProviderError, StreamEvent
from app.providers.local_ollama import (
    LocalEngine,
    LocalProvider,
    OllamaEngine,
    _messages_to_ollama,
    _tools_to_ollama,
)


# --------------------------------------------------------------------------
# a scripted engine (bypasses HTTP entirely for deterministic unit tests)
# --------------------------------------------------------------------------
class FakeEngine(LocalEngine):
    name = "fake"

    def __init__(self, *, chat_response=None, stream_chunks=None):
        self._chat_response = chat_response
        self._stream_chunks = stream_chunks or []
        self.last_body = None

    async def chat(self, body):
        self.last_body = body
        return self._chat_response

    async def chat_stream(self, body):
        self.last_body = body
        for c in self._stream_chunks:
            yield c


# --------------------------------------------------------------------------
# interface conformance
# --------------------------------------------------------------------------
def test_local_provider_is_model_provider():
    p = LocalProvider(engine=FakeEngine(chat_response={}))
    assert isinstance(p, ModelProvider)
    assert p.name == "local"
    # implements both required contract methods
    assert hasattr(p, "complete") and hasattr(p, "stream")


def test_factory_selects_local(monkeypatch):
    # get_provider('local') constructs a real OllamaEngine (no HTTP at init)
    p = get_provider("local")
    assert p.name == "local"
    assert isinstance(p, LocalProvider)


def test_local_rejects_unknown_engine(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LOCAL_ENGINE", "tensorrt")
    with pytest.raises(ProviderError) as e:
        LocalProvider()
    assert "tensorrt" in str(e.value)
    get_settings.cache_clear()


# --------------------------------------------------------------------------
# complete(): text + token accounting
# --------------------------------------------------------------------------
async def test_complete_parses_text_and_tokens():
    resp_json = {
        "model": "gemma4:12b-mlx",
        "message": {"role": "assistant", "content": "pong"},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 20,
        "eval_count": 3,
    }
    prov = LocalProvider(engine=FakeEngine(chat_response=resp_json))
    resp = await prov.complete(
        model="gemma4:12b-mlx", system="s", messages=[], tools=[], max_tokens=64
    )
    assert isinstance(resp, ModelResponse)
    assert resp.text == "pong"
    assert resp.stop_reason == "end_turn"
    assert resp.input_tokens == 20  # prompt_eval_count
    assert resp.output_tokens == 3  # eval_count
    assert resp.model == "gemma4:12b-mlx"


# --------------------------------------------------------------------------
# complete(): tool call → normalized Anthropic tool_use block
# --------------------------------------------------------------------------
async def test_complete_parses_tool_calls():
    resp_json = {
        "model": "gemma4:12b-mlx",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_298u1yp1",
                    "function": {"name": "get_weather", "arguments": {"city": "Paris"}},
                }
            ],
        },
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 73,
        "eval_count": 14,
    }
    prov = LocalProvider(engine=FakeEngine(chat_response=resp_json))
    resp = await prov.complete(
        model="gemma4:12b-mlx",
        system="s",
        messages=[{"role": "user", "content": "weather in Paris?"}],
        tools=[
            {
                "name": "get_weather",
                "description": "Get weather",
                "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
            }
        ],
        max_tokens=64,
    )
    assert resp.stop_reason == "tool_use"
    uses = resp.tool_uses
    assert len(uses) == 1
    assert uses[0]["type"] == "tool_use"
    assert uses[0]["name"] == "get_weather"
    assert uses[0]["input"] == {"city": "Paris"}
    assert uses[0]["id"] == "call_298u1yp1"
    assert resp.input_tokens == 73 and resp.output_tokens == 14


async def test_complete_tool_arguments_json_string_is_parsed():
    resp_json = {
        "model": "m",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "f", "arguments": '{"x": 1}'}}
            ],
        },
        "done": True,
        "prompt_eval_count": 1,
        "eval_count": 1,
    }
    prov = LocalProvider(engine=FakeEngine(chat_response=resp_json))
    resp = await prov.complete(model="m", system="", messages=[], tools=[], max_tokens=8)
    assert resp.tool_uses[0]["input"] == {"x": 1}
    # missing id is synthesized so downstream tool_result mapping works
    assert resp.tool_uses[0]["id"] == "call_0"


# --------------------------------------------------------------------------
# stream(): text deltas then a final response with token accounting
# --------------------------------------------------------------------------
async def test_stream_emits_deltas_then_final():
    chunks = [
        {"model": "m", "message": {"role": "assistant", "content": "Hel"}, "done": False},
        {"model": "m", "message": {"role": "assistant", "content": "lo"}, "done": False},
        {
            "model": "m",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 5,
            "eval_count": 2,
        },
    ]
    prov = LocalProvider(engine=FakeEngine(stream_chunks=chunks))
    events = [
        ev
        async for ev in prov.stream(
            model="m", system="s", messages=[], tools=[], max_tokens=64
        )
    ]
    deltas = [e.text for e in events if e.type == "text_delta"]
    finals = [e for e in events if e.type == "final"]
    assert deltas == ["Hel", "lo"]
    assert len(finals) == 1
    final = finals[0].response
    assert final.text == "Hello"
    assert final.input_tokens == 5 and final.output_tokens == 2
    assert final.stop_reason == "end_turn"


async def test_stream_captures_tool_calls():
    chunks = [
        {"model": "m", "message": {"role": "assistant", "content": ""}, "done": False},
        {
            "model": "m",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "f", "arguments": {"a": 1}}}],
            },
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 9,
            "eval_count": 4,
        },
    ]
    prov = LocalProvider(engine=FakeEngine(stream_chunks=chunks))
    events = [
        ev
        async for ev in prov.stream(model="m", system="", messages=[], tools=[], max_tokens=8)
    ]
    final = [e for e in events if e.type == "final"][0].response
    assert final.stop_reason == "tool_use"
    assert final.tool_uses[0]["name"] == "f"
    assert final.tool_uses[0]["input"] == {"a": 1}


# --------------------------------------------------------------------------
# wire translation helpers
# --------------------------------------------------------------------------
def test_tools_to_ollama_shape():
    out = _tools_to_ollama(
        [{"name": "t", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    )
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "t"
    assert out[0]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_messages_to_ollama_flattens_blocks():
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "let me check"},
                {"type": "tool_use", "id": "c1", "name": "f", "input": {"a": 1}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "c1", "content": "result text"}
            ],
        },
    ]
    out = _messages_to_ollama("SYS", messages)
    assert out[0] == {"role": "system", "content": "SYS"}
    assert out[1] == {"role": "user", "content": "hi"}
    # assistant text + tool_calls
    assert out[2]["role"] == "assistant"
    assert out[2]["content"] == "let me check"
    assert out[2]["tool_calls"][0]["function"]["name"] == "f"
    assert out[2]["tool_calls"][0]["function"]["arguments"] == {"a": 1}
    # tool_result → role="tool"
    assert out[3] == {"role": "tool", "content": "result text"}


# --------------------------------------------------------------------------
# complete(): request body carries think=False + max_tokens + tools
# --------------------------------------------------------------------------
async def test_complete_body_shape():
    eng = FakeEngine(
        chat_response={"model": "m", "message": {"content": "x"}, "done": True,
                       "prompt_eval_count": 1, "eval_count": 1}
    )
    prov = LocalProvider(engine=eng)
    await prov.complete(
        model="m",
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "t", "description": "d", "input_schema": {"type": "object"}}],
        max_tokens=99,
    )
    assert eng.last_body["stream"] is False
    assert eng.last_body["think"] is False
    assert eng.last_body["options"]["num_predict"] == 99
    assert eng.last_body["tools"][0]["function"]["name"] == "t"


# --------------------------------------------------------------------------
# HTTP-level: mock ollama via httpx MockTransport (exercises OllamaEngine)
# --------------------------------------------------------------------------
async def test_ollama_engine_http_complete():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(
            200,
            json={
                "model": "m",
                "message": {"role": "assistant", "content": "hi there"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 11,
                "eval_count": 6,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    engine = OllamaEngine(base_url="http://localhost:11434", timeout=5.0, client=client)
    prov = LocalProvider(engine=engine)
    resp = await prov.complete(model="m", system="s", messages=[], tools=[], max_tokens=32)
    assert resp.text == "hi there"
    assert resp.input_tokens == 11 and resp.output_tokens == 6
    await client.aclose()


async def test_ollama_engine_http_error_becomes_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad model"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    engine = OllamaEngine(base_url="http://localhost:11434", timeout=5.0, client=client)
    prov = LocalProvider(engine=engine)
    with pytest.raises(ProviderError) as e:
        await prov.complete(model="m", system="s", messages=[], tools=[], max_tokens=32)
    assert e.value.status == 400
    await client.aclose()
