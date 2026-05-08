"""Sprint-4 fix #9: Anthropic prompt caching at the runtime layer.

When the system prompt is large enough, we mark the system block with
`cache_control={"type":"ephemeral"}` so subsequent calls hit the 90%
input-token discount (Tier 3). The flag can be turned off via
`prompt_cache=False` (driven by `quill-runtime run --no-cache`).
"""

from __future__ import annotations

from typing import Any

import pytest

import dataclasses

from runtime.config import Config, get_config
from runtime.llm_client import LLMClient, LLMResponse, PROMPT_CACHE_MIN_CHARS


# ---------------------------------------------------------------------------
# Helpers: a fake Anthropic client that captures messages.create kwargs.
# ---------------------------------------------------------------------------
class _FakeUsage:
    def __init__(
        self,
        input_tokens: int = 100,
        output_tokens: int = 50,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


class _FakeBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    def __init__(self, *, text: str = "ok", usage: _FakeUsage | None = None) -> None:
        self.content = [_FakeBlock(text)]
        self.usage = usage or _FakeUsage()


class _FakeMessages:
    def __init__(self, response: _FakeResponse) -> None:
        self.captured: list[dict[str, Any]] = []
        self._response = response

    def create(self, **kwargs):
        self.captured.append(kwargs)
        return self._response


class _FakeAnthropic:
    def __init__(self, response: _FakeResponse) -> None:
        self.messages = _FakeMessages(response)


@pytest.fixture
def fake_config() -> Config:
    base = get_config()
    return dataclasses.replace(base, anthropic_api_key="test-key")


def _client_with_response(cfg: Config, resp: _FakeResponse) -> tuple[LLMClient, _FakeAnthropic]:
    fake = _FakeAnthropic(resp)
    return (
        LLMClient(config=cfg, client_factory=lambda _c: fake),
        fake,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cache_control_sent_for_large_system_prompt(fake_config) -> None:
    big_system = "X" * (PROMPT_CACHE_MIN_CHARS + 100)
    client, fake = _client_with_response(
        fake_config, _FakeResponse(text="hi", usage=_FakeUsage())
    )

    resp = await client.call_llm(
        model="claude-opus-4-7", system=big_system, user="hello"
    )

    assert resp.cache_used is True
    sent = fake.messages.captured[0]
    sys_param = sent["system"]
    assert isinstance(sys_param, list), "large prompts must be sent as a block list"
    assert sys_param[0]["cache_control"] == {"type": "ephemeral"}
    assert sys_param[0]["text"] == big_system


@pytest.mark.asyncio
async def test_cache_control_skipped_for_small_system_prompt(fake_config) -> None:
    tiny_system = "short prompt"
    client, fake = _client_with_response(fake_config, _FakeResponse())

    resp = await client.call_llm(
        model="claude-opus-4-7", system=tiny_system, user="hi"
    )
    assert resp.cache_used is False
    sent = fake.messages.captured[0]
    # Plain string, no cache_control overhead.
    assert sent["system"] == tiny_system


@pytest.mark.asyncio
async def test_no_cache_flag_disables_caching(fake_config) -> None:
    big_system = "Y" * (PROMPT_CACHE_MIN_CHARS + 1)
    client, fake = _client_with_response(fake_config, _FakeResponse())

    resp = await client.call_llm(
        model="claude-opus-4-7",
        system=big_system,
        user="hi",
        prompt_cache=False,
    )
    assert resp.cache_used is False
    sent = fake.messages.captured[0]
    assert sent["system"] == big_system


@pytest.mark.asyncio
async def test_cache_hit_metric_recorded(fake_config) -> None:
    big_system = "Z" * (PROMPT_CACHE_MIN_CHARS + 1)
    usage = _FakeUsage(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=2048,
    )
    client, _fake = _client_with_response(fake_config, _FakeResponse(usage=usage))

    resp = await client.call_llm(
        model="claude-opus-4-7", system=big_system, user="hi"
    )
    assert resp.cache_hit is True
    assert resp.cache_read_input_tokens == 2048
    assert resp.cache_creation_input_tokens == 0


@pytest.mark.asyncio
async def test_cache_miss_creates_entry(fake_config) -> None:
    big_system = "W" * (PROMPT_CACHE_MIN_CHARS + 1)
    usage = _FakeUsage(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=4096,
        cache_read_input_tokens=0,
    )
    client, _fake = _client_with_response(fake_config, _FakeResponse(usage=usage))

    resp = await client.call_llm(
        model="claude-opus-4-7", system=big_system, user="hi"
    )
    assert resp.cache_hit is False
    assert resp.cache_creation_input_tokens == 4096
