"""ModelProvider interface + shared retry/backoff.

A provider turns (model, system, messages, tools) into a ModelResponse with
normalized content blocks and token usage. Cutover between Anthropic-direct
and Vertex is config (MODEL_PROVIDER), not code — SPIKE_FINDINGS action item.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

log = logging.getLogger("agentcloud.providers")

T = TypeVar("T")


class ProviderError(RuntimeError):
    """Terminal provider failure (bad config, quota exhausted, retries spent)."""

    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class LocalUnreachableError(ProviderError):
    """The on-prem (local) inference host could not be reached at all — a
    transport/connection failure, not a model or request error. Signals the
    fail-open wrapper that it is safe to degrade this turn to the frontier
    provider (the host is down, nothing sensitive was processed locally).
    A genuine model/API error stays a plain ProviderError and does NOT
    fail-open (we must not leak a bad-request retry to the cloud).
    """


@dataclass
class ModelResponse:
    content: list[dict[str, Any]]  # normalized Anthropic-style blocks
    stop_reason: str | None
    model: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def text(self) -> str:
        return "".join(
            b.get("text", "") for b in self.content if b.get("type") == "text"
        )

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") == "tool_use"]


@dataclass
class StreamEvent:
    """Streaming event: type in {text_delta, final}."""

    type: str
    text: str = ""
    response: ModelResponse | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class ModelProvider(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> ModelResponse: ...

    def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        """Default: fall back to complete() and emit the text in one chunk."""

        async def _gen() -> AsyncIterator[StreamEvent]:
            resp = await self.complete(
                model=model,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
            )
            if resp.text:
                yield StreamEvent(type="text_delta", text=resp.text)
            yield StreamEvent(type="final", response=resp)

        return _gen()


async def with_retries(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    base_delay: float,
    is_retryable: Callable[[Exception], bool],
    what: str,
) -> T:
    """Exponential backoff with jitter: base_delay * 2^n + U(0, 0.25s)."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 — classified below
            last = exc
            if not is_retryable(exc) or attempt == attempts - 1:
                raise
            delay = base_delay * (2**attempt) + random.uniform(0, 0.25)
            log.warning(
                "retryable provider error on %s (attempt %d/%d): %s — sleeping %.2fs",
                what,
                attempt + 1,
                attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    raise ProviderError(f"{what}: retries exhausted: {last}")  # pragma: no cover
