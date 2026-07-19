"""Anthropic API direct provider (live today; ANTHROPIC_API_KEY from Secret Manager)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from app.config import get_settings
from app.providers.base import (
    ModelProvider,
    ModelResponse,
    ProviderError,
    StreamEvent,
    with_retries,
)

log = logging.getLogger("agentcloud.providers.anthropic")

_RETRYABLE = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, _RETRYABLE):
        return True
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code in (429, 500, 502, 503, 529):
        return True
    return False


def _normalize(msg: anthropic.types.Message) -> ModelResponse:
    usage = msg.usage
    return ModelResponse(
        content=[b.model_dump(exclude_none=True) for b in msg.content],
        stop_reason=msg.stop_reason,
        model=msg.model,
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )


# ---------------------------------------------------------------------------
# Prompt caching helpers
#
# Anthropic prompt caching charges cached prefixes at ~10% on reuse (with a
# one-time ~25% write surcharge). It only helps for byte-identical, front-of-
# prompt content, and it does NOT change model output. Our best-value, always-
# identical prefixes per agent turn are the TOOL definitions and the SYSTEM
# prompt, so we mark those. The variable part (messages / the user's request)
# is never cached. Gated by settings.PROMPT_CACHE_ENABLED (default on) so it
# can be flipped off without a code change if ever needed.
# ---------------------------------------------------------------------------
_CACHE_CONTROL = {"type": "ephemeral"}


def _cache_enabled() -> bool:
    return bool(getattr(get_settings(), "PROMPT_CACHE_ENABLED", True))


def _cached_system(system: str) -> Any:
    """Convert a system string into a single cached content block.

    Returns the original string unchanged when caching is disabled or the
    system prompt is empty/whitespace (nothing worth a cache breakpoint).
    """
    if not _cache_enabled() or not system or not system.strip():
        return system
    return [{"type": "text", "text": system, "cache_control": _CACHE_CONTROL}]


def _cached_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark the LAST tool with cache_control so the whole tools array is cached.

    A single breakpoint on the final tool caches every tool definition before
    it (Anthropic caches the prefix up to and including the marked block).
    Returns tools unchanged when caching is disabled or there are no tools.
    Does not mutate the caller's list.
    """
    if not _cache_enabled() or not tools:
        return tools
    out = [dict(t) for t in tools]
    out[-1] = {**out[-1], "cache_control": _CACHE_CONTROL}
    return out


class AnthropicDirectProvider(ModelProvider):
    name = "anthropic"

    def __init__(self, client: anthropic.AsyncAnthropic | None = None):
        # SDK retries disabled — our with_retries() owns backoff policy.
        self._client = client or anthropic.AsyncAnthropic(max_retries=0)
        self._settings = get_settings()

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> ModelResponse:
        s = self._settings

        cached_system = _cached_system(system)
        cached_tools = _cached_tools(tools)

        async def _call() -> ModelResponse:
            msg = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=cached_system,
                tools=cached_tools,
                messages=messages,
            )
            return _normalize(msg)

        try:
            return await with_retries(
                _call,
                attempts=s.MODEL_RETRY_ATTEMPTS,
                base_delay=s.MODEL_RETRY_BASE_DELAY,
                is_retryable=_is_retryable,
                what=f"anthropic.complete({model})",
            )
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                f"anthropic API error {exc.status_code}: {exc.message}",
                status=exc.status_code,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"anthropic connection error: {exc}") from exc

    def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        cached_system = _cached_system(system)
        cached_tools = _cached_tools(tools)

        async def _gen() -> AsyncIterator[StreamEvent]:
            try:
                async with self._client.messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    system=cached_system,
                    tools=cached_tools,
                    messages=messages,
                ) as stream:
                    async for text in stream.text_stream:
                        if text:
                            yield StreamEvent(type="text_delta", text=text)
                    final = await stream.get_final_message()
                yield StreamEvent(type="final", response=_normalize(final))
            except anthropic.APIStatusError as exc:
                raise ProviderError(
                    f"anthropic stream error {exc.status_code}: {exc.message}",
                    status=exc.status_code,
                ) from exc
            except anthropic.APIConnectionError as exc:
                raise ProviderError(f"anthropic stream connection error: {exc}") from exc

        return _gen()
