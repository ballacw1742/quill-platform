"""Model routing layer: pick local (Ollama) vs remote (Anthropic) per call.

Spec: see `MODEL_ROUTING_CONTRACT.md` in this directory. This module is the
single place that decides which backend handles a given agent invocation.

The routing decision is driven by:
  1. CLI/env override (``DEFAULT_MODEL_OVERRIDE`` or ``model_override``)
  2. Kill switch (``LOCAL_DISABLE=1`` forces remote)
  3. Agent front-matter ``cost_class`` (default ``remote-only``)

Returns the canonical `LLMResponse` either way so callers stay
backend-agnostic.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import structlog

from runtime.agent_loader import AgentSpec
from runtime.llm_client import LLMClient, LLMError, LLMResponse
from runtime.local_llm_client import LocalLLMClient, LocalLLMError

log = structlog.get_logger(__name__)


# Acceptable values for cost_class. Anything outside this set is treated as
# remote-only (safer default) and a warning is logged.
_VALID_COST_CLASSES = {
    "remote-only",
    "remote-preferred",  # alias
    "local-preferred",
    "local-only",
}


@dataclass(frozen=True)
class RoutingDecision:
    backend: str  # "anthropic" | "ollama"
    model: str
    fallback_model: str | None  # remote model used if local fails (local-preferred)
    reason: str  # short human-readable explanation, logged at INFO


def _is_local_disabled() -> bool:
    return os.environ.get("LOCAL_DISABLE", "").lower() in {"1", "true", "yes"}


def _backend_for_model_name(name: str) -> str:
    """Pick a backend purely from a model name. Anthropic models start with
    ``claude-``; everything else (gemma*, qwen*, llama*, …) routes local."""
    return "anthropic" if name.startswith("claude-") else "ollama"


def decide_route(
    spec: AgentSpec,
    *,
    model_override: str | None = None,
    config_default_override: str | None = None,
) -> RoutingDecision:
    """Resolve the routing decision for one call.

    Precedence (highest to lowest):
      1. ``model_override`` (CLI ``--model``)
      2. ``config_default_override`` (``DEFAULT_MODEL_OVERRIDE`` env var)
      3. Kill switch (``LOCAL_DISABLE=1``) forces remote
      4. Agent front-matter ``cost_class``
    """
    fm = spec.raw_frontmatter or {}
    cost_class = (fm.get("cost_class") or "remote-only").strip().lower()
    if cost_class not in _VALID_COST_CLASSES:
        log.warning(
            "model_router.invalid_cost_class",
            agent_id=spec.agent_id,
            value=cost_class,
            default_applied="remote-only",
        )
        cost_class = "remote-only"
    local_model = fm.get("local_model") or os.environ.get(
        "LOCAL_MODEL_NAME", "gemma4:12b-mlx"
    )

    # 1+2: explicit overrides win.
    explicit = model_override or config_default_override
    if explicit:
        backend = _backend_for_model_name(explicit)
        return RoutingDecision(
            backend=backend,
            model=explicit,
            fallback_model=None,
            reason=f"override({explicit})",
        )

    # 3: kill switch.
    if _is_local_disabled() and cost_class in {"local-preferred", "local-only"}:
        return RoutingDecision(
            backend="anthropic",
            model=spec.default_model,
            fallback_model=None,
            reason=f"local_disabled_kill_switch (was {cost_class})",
        )

    # 4: front-matter.
    if cost_class in {"remote-only", "remote-preferred"}:
        return RoutingDecision(
            backend="anthropic",
            model=spec.default_model,
            fallback_model=None,
            reason=f"cost_class={cost_class}",
        )
    if cost_class == "local-preferred":
        return RoutingDecision(
            backend="ollama",
            model=local_model,
            fallback_model=spec.default_model,
            reason="cost_class=local-preferred",
        )
    if cost_class == "local-only":
        return RoutingDecision(
            backend="ollama",
            model=local_model,
            fallback_model=None,
            reason="cost_class=local-only",
        )

    # Defensive — should be unreachable after validation above.
    return RoutingDecision(
        backend="anthropic",
        model=spec.default_model,
        fallback_model=None,
        reason="fallback_default",
    )


class ModelRouter:
    """Backend-agnostic call dispatcher.

    Built once per agent (or once per process). Reuses the underlying
    ``LLMClient`` (Anthropic) and ``LocalLLMClient`` (Ollama) instances.
    """

    def __init__(
        self,
        remote_client: LLMClient | None = None,
        local_client: LocalLLMClient | None = None,
    ) -> None:
        self._remote = remote_client or LLMClient()
        self._local = local_client or LocalLLMClient()

    async def call(
        self,
        *,
        spec: AgentSpec,
        system: str,
        user: str,
        model_override: str | None = None,
        config_default_override: str | None = None,
        max_tokens: int = 16000,
        temperature: float = 0.0,
        prompt_cache: bool = True,
        images: list[str] | None = None,
    ) -> LLMResponse:
        decision = decide_route(
            spec,
            model_override=model_override,
            config_default_override=config_default_override,
        )
        log.info(
            "llm.route.decision",
            agent_id=spec.agent_id,
            backend=decision.backend,
            model=decision.model,
            reason=decision.reason,
            fallback_model=decision.fallback_model,
        )

        if decision.backend == "anthropic":
            if images:
                # Anthropic multimodal would need messages with image blocks;
                # for now Phase-2 multimodal is local-only. Surface clearly.
                log.warning(
                    "llm.route.images_unsupported_for_remote",
                    agent_id=spec.agent_id,
                    n_images=len(images),
                )
            return await self._remote.call_llm(
                model=decision.model,
                system=system,
                user=user,
                max_tokens=max_tokens,
                temperature=temperature,
                upgrade_model=spec.upgrade_model,
                prompt_cache=prompt_cache,
            )

        # Local path
        start = time.perf_counter()
        try:
            local_resp = await self._local.call(
                model=decision.model,
                system=system,
                user=user,
                images=images,
                temperature=temperature,
            )
            return LLMResponse(
                text=local_resp["text"],
                model_used=local_resp["model_used"],
                input_tokens=local_resp["input_tokens"],
                output_tokens=local_resp["output_tokens"],
                latency_ms=local_resp["latency_ms"],
                attempts=1,
                fell_back=False,
                cache_hit=False,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
                cache_used=False,
                backend="ollama",
            )
        except LocalLLMError as e:
            if decision.fallback_model is None:
                # local-only: surface the failure.
                log.error(
                    "llm.route.local_only_fail",
                    agent_id=spec.agent_id,
                    model=decision.model,
                    err=str(e),
                )
                raise LLMError(f"local call failed (no fallback): {e}") from e

            # local-preferred: fall back to remote.
            log.warning(
                "llm.route.local_fallback",
                agent_id=spec.agent_id,
                from_model=decision.model,
                to_model=decision.fallback_model,
                err=str(e),
            )
            resp = await self._remote.call_llm(
                model=decision.fallback_model,
                system=system,
                user=user,
                max_tokens=max_tokens,
                temperature=temperature,
                upgrade_model=spec.upgrade_model,
                prompt_cache=prompt_cache,
            )
            # Mark the response as having fallen back from local.
            resp.fell_back = True
            return resp


__all__ = ["ModelRouter", "RoutingDecision", "decide_route"]
