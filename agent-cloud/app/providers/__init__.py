"""Model providers. Switch with MODEL_PROVIDER=anthropic|vertex|local."""

from __future__ import annotations

from app.config import get_settings
from app.providers.base import ModelProvider, ModelResponse, ProviderError, StreamEvent


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


def get_provider_for_lane(lane: str | None) -> ModelProvider:
    """Provider for a per-agent lane when MODEL_LANE_ROUTING_ENABLED is on.

    When routing is disabled, the global MODEL_PROVIDER is used (unchanged
    legacy behavior) so this is a safe no-op until the flag is flipped.
    """
    if not get_settings().MODEL_LANE_ROUTING_ENABLED:
        return get_provider()
    return get_provider(provider_name_for_lane(lane))


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
    "StreamEvent",
    "get_provider",
    "get_provider_for_lane",
    "provider_name_for_lane",
    "model_for_lane",
    "LANE_LOCAL",
    "LANE_FRONTIER",
    "MODEL_LANES",
]
