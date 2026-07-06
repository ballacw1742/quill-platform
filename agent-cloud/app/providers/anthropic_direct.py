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
    return ModelResponse(
        content=[b.model_dump(exclude_none=True) for b in msg.content],
        stop_reason=msg.stop_reason,
        model=msg.model,
        input_tokens=msg.usage.input_tokens if msg.usage else 0,
        output_tokens=msg.usage.output_tokens if msg.usage else 0,
    )


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

        async def _call() -> ModelResponse:
            msg = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                tools=tools,
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
        async def _gen() -> AsyncIterator[StreamEvent]:
            try:
                async with self._client.messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    tools=tools,
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
