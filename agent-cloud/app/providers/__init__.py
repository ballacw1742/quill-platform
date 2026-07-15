"""Model providers. Switch with MODEL_PROVIDER=anthropic|vertex|local."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.config import get_settings
from app.providers.base import (
    LocalUnreachableError,
    ModelProvider,
    ModelResponse,
    ProviderError,
    StreamEvent,
)

log = logging.getLogger("agentcloud.providers")


def get_provider(name: str | None = None) -> ModelProvider:
    provider = (name or get_settings().MODEL_PROVIDER).strip().lower()
    if provider == "anthropic":
        from app.providers.anthropic_direct import AnthropicDirectProvider

        return AnthropicDirectProvider()
    if provider == "vertex":
        from app.providers.vertex_anthropic import VertexAnthropicProvider

        return VertexAnthropicProvider()
    if provider == "local":
        from app.providers.local_ollama import LocalProvider

        return LocalProvider()
    raise ProviderError(
        f"unknown MODEL_PROVIDER '{provider}' "
        "(expected 'anthropic', 'vertex', or 'local')"
    )


# Hybrid Sensitivity Router (scaled-down §8) -----------------------------------
# The two lanes an agent can be assigned. "local" is the fail-safe: any
# unknown/unclassified value resolves to the local lane so data never leaves
# the box by accident.
LANE_LOCAL = "local"
LANE_FRONTIER = "frontier"
MODEL_LANES = (LANE_LOCAL, LANE_FRONTIER)


def provider_name_for_lane(lane: str | None) -> str:
    """Resolve an agent's model_lane to the configured provider name.

    Fail-safe: anything other than an explicit 'frontier' lane maps to the
    local provider, so a new/unclassified agent keeps its data on-prem.
    """
    s = get_settings()
    if (lane or "").strip().lower() == LANE_FRONTIER:
        return s.LANE_FRONTIER_PROVIDER
    return s.LANE_LOCAL_PROVIDER


class FailOpenProvider(ModelProvider):
    """Wraps a LOCAL provider with a frontier fallback (§8 fail-open).

    Normal path: delegate to the local (on-prem) provider. If — and ONLY if —
    the local host is unreachable (LocalUnreachableError: a transport/
    connection failure, e.g. the Mac Studio is asleep or off the tailnet), the
    turn is degraded to the frontier provider so the product stays up. A
    genuine model/API error is re-raised unchanged (never fails open — we must
    not retry a bad local request against the cloud).

    The degradation is loud: a WARNING is logged every time it fires. This is
    a deliberate demo-phase tradeoff; set MODEL_LANE_FAIL_OPEN=False for the
    absolute fail-closed guarantee.
    """

    name = "failopen-local"

    def __init__(self, local: ModelProvider, frontier: ModelProvider, frontier_model: str):
        self._local = local
        self._frontier = frontier
        self._frontier_model = frontier_model

    async def complete(self, *, model, system, messages, tools, max_tokens) -> ModelResponse:
        try:
            return await self._local.complete(
                model=model, system=system, messages=messages,
                tools=tools, max_tokens=max_tokens,
            )
        except LocalUnreachableError as exc:
            log.warning(
                "FAIL-OPEN: local inference unreachable (%s) — degrading this "
                "turn to frontier provider %r/%s. Sensitive-data turns may "
                "transit the cloud until local inference is restored.",
                exc, self._frontier.name, self._frontier_model,
            )
            return await self._frontier.complete(
                model=self._frontier_model, system=system, messages=messages,
                tools=tools, max_tokens=max_tokens,
            )

    def stream(self, *, model, system, messages, tools, max_tokens) -> AsyncIterator[StreamEvent]:
        frontier = self._frontier
        frontier_model = self._frontier_model
        local = self._local

        async def _gen() -> AsyncIterator[StreamEvent]:
            # Probe the local stream; if the FIRST pull fails with an
            # unreachable error (before any token was yielded), degrade to
            # frontier. A mid-stream failure can't be safely re-tried, so it
            # propagates (rare: connection dropped after tokens started).
            try:
                agen = local.stream(
                    model=model, system=system, messages=messages,
                    tools=tools, max_tokens=max_tokens,
                )
                first = await agen.__anext__()
            except StopAsyncIteration:
                return
            except LocalUnreachableError as exc:
                log.warning(
                    "FAIL-OPEN (stream): local inference unreachable (%s) — "
                    "degrading to frontier %r/%s.",
                    exc, frontier.name, frontier_model,
                )
                async for ev in frontier.stream(
                    model=frontier_model, system=system, messages=messages,
                    tools=tools, max_tokens=max_tokens,
                ):
                    yield ev
                return
            yield first
            async for ev in agen:
                yield ev

        return _gen()


def get_provider_for_lane(lane: str | None) -> ModelProvider:
    """Provider for a per-agent lane when MODEL_LANE_ROUTING_ENABLED is on.

    When routing is disabled, the global MODEL_PROVIDER is used (unchanged
    legacy behavior) so this is a safe no-op until the flag is flipped.

    For the LOCAL lane, when MODEL_LANE_FAIL_OPEN is set, the local provider is
    wrapped in a FailOpenProvider that degrades to frontier if the on-prem
    host is unreachable.
    """
    s = get_settings()
    if not s.MODEL_LANE_ROUTING_ENABLED:
        return get_provider()
    name = provider_name_for_lane(lane)
    prov = get_provider(name)
    # Fail-open only applies to the local lane (frontier has nothing to fall
    # back to). Skip wrapping if the local and frontier providers are the same.
    if (
        s.MODEL_LANE_FAIL_OPEN
        and (lane or "").strip().lower() == LANE_LOCAL
        and s.LANE_FRONTIER_PROVIDER.strip().lower()
        != s.LANE_LOCAL_PROVIDER.strip().lower()
    ):
        frontier = get_provider(s.LANE_FRONTIER_PROVIDER)
        return FailOpenProvider(prov, frontier, s.MODEL_DEFAULT)
    return prov


def _is_local_model_id(model: str | None) -> bool:
    """True when a model id is an on-prem (ollama) id rather than a Claude id.
    Local ids are prefixed local:/ollama: (pricing.ZERO_COST_PREFIXES) or the
    canonical 'local'. Anything else (e.g. claude-*) is a frontier id."""
    m = (model or "").strip().lower()
    return m == "local" or m.startswith(("local:", "ollama:"))


def model_for_lane(lane: str | None, agent_model: str | None) -> str:
    """The model id to run for a lane (only consulted when lane routing is on).

    The lane's provider is authoritative: a local-lane agent must run a local
    model id (an ollama engine can't run 'claude-fable-5'), and a frontier
    agent must run a Claude id. The agent's own pinned `model` is honored ONLY
    when it is compatible with the lane; otherwise the lane default is used.
    This lets an agent seeded with a Claude model be safely re-lane'd to local
    without hand-editing its model column.
    """
    s = get_settings()
    frontier = (lane or "").strip().lower() == LANE_FRONTIER
    if frontier:
        # frontier lane wants a Claude id; ignore a stray local id.
        if agent_model and not _is_local_model_id(agent_model):
            return agent_model
        return s.MODEL_DEFAULT
    # local lane wants an on-prem id; ignore a stray Claude id.
    if agent_model and _is_local_model_id(agent_model):
        return agent_model
    return s.MODEL_LOCAL_DEFAULT


__all__ = [
    "ModelProvider",
    "ModelResponse",
    "ProviderError",
    "LocalUnreachableError",
    "StreamEvent",
    "get_provider",
    "get_provider_for_lane",
    "provider_name_for_lane",
    "model_for_lane",
    "FailOpenProvider",
    "LANE_LOCAL",
    "LANE_FRONTIER",
    "MODEL_LANES",
]
