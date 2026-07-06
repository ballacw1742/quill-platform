import httpx
import pytest

import anthropic

from app.providers import get_provider
from app.providers.base import ModelResponse, ProviderError, with_retries
from app.providers.vertex_anthropic import VertexAnthropicProvider


def _status_error(status: int) -> anthropic.APIStatusError:
    req = httpx.Request("POST", "https://api.example/v1/messages")
    resp = httpx.Response(status, request=req, json={"error": {"message": "boom"}})
    cls = {
        429: anthropic.RateLimitError,
        500: anthropic.InternalServerError,
    }.get(status, anthropic.APIStatusError)
    return cls("boom", response=resp, body=None)


# --------------------------- retry/backoff ----------------------------------


async def test_with_retries_retries_then_succeeds():
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _status_error(429)
        return "ok"

    out = await with_retries(
        flaky, attempts=3, base_delay=0.01,
        is_retryable=lambda e: True, what="test",
    )
    assert out == "ok"
    assert attempts["n"] == 3


async def test_with_retries_gives_up_after_attempts():
    async def always_fails():
        raise _status_error(429)

    with pytest.raises(anthropic.RateLimitError):
        await with_retries(
            always_fails, attempts=2, base_delay=0.01,
            is_retryable=lambda e: True, what="test",
        )


async def test_with_retries_does_not_retry_terminal_errors():
    attempts = {"n": 0}

    async def bad_request():
        attempts["n"] += 1
        raise _status_error(400)

    with pytest.raises(anthropic.APIStatusError):
        await with_retries(
            bad_request, attempts=3, base_delay=0.01,
            is_retryable=lambda e: isinstance(e, anthropic.RateLimitError),
            what="test",
        )
    assert attempts["n"] == 1


# --------------------------- provider factory --------------------------------


def test_factory_selects_anthropic():
    assert get_provider("anthropic").name == "anthropic"


def test_factory_rejects_unknown():
    with pytest.raises(ProviderError):
        get_provider("bard")


# --------------------------- vertex clean-error path ------------------------


class _FakeVertexMessages:
    async def create(self, **kwargs):
        raise _status_error(429)


class _FakeVertexClient:
    messages = _FakeVertexMessages()


async def test_vertex_quota_zero_errors_cleanly_with_hint():
    provider = VertexAnthropicProvider(client=_FakeVertexClient())
    with pytest.raises(ProviderError) as exc_info:
        await provider.complete(
            model="claude-haiku-4-5", system="s", messages=[], tools=[], max_tokens=64
        )
    msg = str(exc_info.value)
    assert "429" in msg
    assert "MODEL_PROVIDER=anthropic" in msg  # actionable, not silent


async def test_vertex_success_normalizes(monkeypatch):
    class _Msg:
        def __init__(self):
            self.stop_reason = "end_turn"
            self.model = "claude-haiku-4-5"

            class U:
                input_tokens = 5
                output_tokens = 7

            self.usage = U()
            import types

            block = types.SimpleNamespace()
            block.model_dump = lambda exclude_none=True: {"type": "text", "text": "vertex ok"}
            self.content = [block]

    class _Messages:
        async def create(self, **kwargs):
            return _Msg()

    class _Client:
        messages = _Messages()

    provider = VertexAnthropicProvider(client=_Client())
    resp = await provider.complete(
        model="claude-haiku-4-5", system="s", messages=[], tools=[], max_tokens=64
    )
    assert isinstance(resp, ModelResponse)
    assert resp.text == "vertex ok"
    assert resp.input_tokens == 5
