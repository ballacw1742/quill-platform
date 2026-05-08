"""Thin Anthropic SDK wrapper with retries, rate-limit fallback, and observability."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from runtime.config import Config, get_config

log = structlog.get_logger(__name__)


# Anthropic charges based on a rough 4-chars-per-token heuristic. The cache
# only kicks in for blocks >= 1024 tokens, so we use a conservative ≈4000
# character floor before bothering to mark a block as cacheable.
PROMPT_CACHE_MIN_CHARS = 4000


@dataclass
class LLMResponse:
    text: str
    model_used: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    attempts: int
    fell_back: bool = False
    cache_hit: bool = False
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_used: bool = False


class LLMError(RuntimeError):
    """Generic LLM call failure (after retries / fallback)."""


def _backoff_seconds(attempt: int, *, ceiling: float = 60.0) -> float:
    base = min(ceiling, 2 ** attempt)
    return base + random.uniform(0, 0.5)


def _is_rate_limit(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    if "ratelimit" in name or "rate_limit" in name:
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    return status == 429


def _is_overloaded(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    if "overloaded" in name:
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    return status in (529, 503)


def _is_retryable(exc: BaseException) -> bool:
    if _is_rate_limit(exc) or _is_overloaded(exc):
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    return status in (500, 502, 504)


class LLMClient:
    """Anthropic-flavored client with retries and an optional upgrade-model fallback.

    The client is lazy about importing the Anthropic SDK so unit tests can avoid
    it entirely (we mock at the `LLMClient.call_llm` level).
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        client_factory: Callable[[Config], Any] | None = None,
    ) -> None:
        self.config = config or get_config()
        self._factory = client_factory
        self._client: Any | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _build_client(self) -> Any:
        if self._factory is not None:
            return self._factory(self.config)
        try:
            from anthropic import Anthropic  # type: ignore
        except ImportError as e:  # pragma: no cover - exercised only without the SDK
            raise LLMError("anthropic SDK not installed") from e
        if not self.config.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        return Anthropic(api_key=self.config.anthropic_api_key)

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    # ------------------------------------------------------------------
    # Main entrypoint
    # ------------------------------------------------------------------
    async def call_llm(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 2000,
        temperature: float = 0.0,
        upgrade_model: str | None = None,
        max_attempts: int = 5,
        prompt_cache: bool = True,
    ) -> LLMResponse:
        """Call the LLM with retries; fall back to `upgrade_model` on rate-limit.

        Sprint-4 fix #9: when ``prompt_cache=True`` (default) and the system
        prompt is large enough to benefit from caching, we wrap the system
        block with ``cache_control={"type":"ephemeral"}``. Anthropic Tier-3
        accounts get a ~90% input-token discount on cache hits.
        """
        return await asyncio.to_thread(
            self._call_sync,
            model=model,
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=temperature,
            upgrade_model=upgrade_model,
            max_attempts=max_attempts,
            prompt_cache=prompt_cache,
        )

    # ------------------------------------------------------------------
    # Sync core (we wrap to a thread so callers stay async-friendly)
    # ------------------------------------------------------------------
    def _call_sync(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
        upgrade_model: str | None,
        max_attempts: int,
        prompt_cache: bool = True,
    ) -> LLMResponse:
        attempt = 0
        active_model = model
        fell_back = False
        last_exc: BaseException | None = None
        start = time.perf_counter()

        # Sprint-4 fix #9: build the system parameter as either a plain string
        # (small prompts — caching wouldn't help) or a structured block list
        # with ephemeral cache_control.
        cache_used = bool(prompt_cache and len(system) >= PROMPT_CACHE_MIN_CHARS)
        system_param: Any
        if cache_used:
            system_param = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            system_param = system

        while attempt < max_attempts:
            attempt += 1
            try:
                resp = self.client.messages.create(
                    model=active_model,
                    system=system_param,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[{"role": "user", "content": user}],
                )
                text = self._extract_text(resp)
                in_tok, out_tok = self._extract_tokens(resp)
                cache_creation, cache_read = self._extract_cache_tokens(resp)
                cache_hit = cache_read > 0
                latency_ms = int((time.perf_counter() - start) * 1000)
                log.info(
                    "llm.call.ok",
                    model=active_model,
                    attempts=attempt,
                    fell_back=fell_back,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cache_used=cache_used,
                    cache_hit=cache_hit,
                    cache_creation_input_tokens=cache_creation,
                    cache_read_input_tokens=cache_read,
                    latency_ms=latency_ms,
                )
                return LLMResponse(
                    text=text,
                    model_used=active_model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    latency_ms=latency_ms,
                    attempts=attempt,
                    fell_back=fell_back,
                    cache_hit=cache_hit,
                    cache_creation_input_tokens=cache_creation,
                    cache_read_input_tokens=cache_read,
                    cache_used=cache_used,
                )
            except BaseException as exc:  # noqa: BLE001
                last_exc = exc
                rate_limited = _is_rate_limit(exc)
                if rate_limited and upgrade_model and active_model != upgrade_model and not fell_back:
                    log.warning(
                        "llm.call.rate_limit_fallback",
                        from_model=active_model,
                        to_model=upgrade_model,
                    )
                    active_model = upgrade_model
                    fell_back = True
                    continue
                if not _is_retryable(exc) or attempt >= max_attempts:
                    log.error(
                        "llm.call.fail",
                        model=active_model,
                        attempts=attempt,
                        err=str(exc),
                        err_type=type(exc).__name__,
                    )
                    raise LLMError(f"LLM call failed after {attempt} attempts: {exc}") from exc
                wait = _backoff_seconds(attempt)
                log.warning(
                    "llm.call.retry",
                    model=active_model,
                    attempt=attempt,
                    wait_s=round(wait, 2),
                    err=str(exc),
                )
                time.sleep(wait)

        # Defensive — should be unreachable
        raise LLMError(f"LLM call failed after {attempt} attempts: {last_exc}")

    # ------------------------------------------------------------------
    # Response shape adapters (Anthropic SDK ≥0.18)
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_text(resp: Any) -> str:
        # Anthropic returns content blocks; we want concatenated text blocks.
        blocks = getattr(resp, "content", None)
        if blocks is None and isinstance(resp, dict):
            blocks = resp.get("content")
        if blocks is None:
            return ""
        parts: list[str] = []
        for blk in blocks:
            if hasattr(blk, "text"):
                parts.append(blk.text or "")
            elif isinstance(blk, dict) and blk.get("type") == "text":
                parts.append(blk.get("text", ""))
        return "".join(parts).strip()

    @staticmethod
    def _extract_tokens(resp: Any) -> tuple[int, int]:
        usage = getattr(resp, "usage", None)
        if usage is None and isinstance(resp, dict):
            usage = resp.get("usage")
        if usage is None:
            return (0, 0)
        in_tok = getattr(usage, "input_tokens", None)
        out_tok = getattr(usage, "output_tokens", None)
        if in_tok is None and isinstance(usage, dict):
            in_tok = usage.get("input_tokens", 0)
            out_tok = usage.get("output_tokens", 0)
        return (int(in_tok or 0), int(out_tok or 0))

    @staticmethod
    def _extract_cache_tokens(resp: Any) -> tuple[int, int]:
        """Pull cache_creation_input_tokens and cache_read_input_tokens off
        an Anthropic Usage object. Returns (creation, read) — zero on miss.
        """
        usage = getattr(resp, "usage", None)
        if usage is None and isinstance(resp, dict):
            usage = resp.get("usage")
        if usage is None:
            return (0, 0)

        def _attr(name: str) -> int:
            v = getattr(usage, name, None)
            if v is None and isinstance(usage, dict):
                v = usage.get(name)
            try:
                return int(v or 0)
            except (TypeError, ValueError):
                return 0

        return (
            _attr("cache_creation_input_tokens"),
            _attr("cache_read_input_tokens"),
        )


__all__ = ["LLMClient", "LLMResponse", "LLMError"]
