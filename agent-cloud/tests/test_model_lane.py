"""Hybrid Sensitivity Router (scaled-down §8): per-agent model-lane routing.

An agent's `model_lane` ('local' | 'frontier') selects the model PROVIDER per
agent instead of the single global MODEL_PROVIDER:

  * local    — on-prem inference (ollama). Sensitive data (cost numbers,
               quantities, confidential business figures) never leaves the box.
               This is the FAIL-SAFE default: an unknown/unclassified lane
               resolves here.
  * frontier — the Claude API, for agents that do NOT touch sensitive data.

The router is gated behind MODEL_LANE_ROUTING_ENABLED; when it's off every
agent uses the global provider exactly as before (backward compatible).
"""

from __future__ import annotations

import pytest

import app.config as config_mod
import app.providers as providers_mod
from app.providers import (
    FailOpenProvider,
    LANE_FRONTIER,
    LANE_LOCAL,
    get_provider_for_lane,
    model_for_lane,
    provider_name_for_lane,
)
from app.providers.base import LocalUnreachableError, ModelResponse, ProviderError


def _fresh_settings(monkeypatch, **overrides):
    """Rebuild Settings with env overrides and clear the lru_cache so both
    the config module and the providers module see the new values."""
    for k, v in overrides.items():
        monkeypatch.setenv(k, str(v))
    config_mod.get_settings.cache_clear()
    return config_mod.get_settings()


# --------------------------- lane → provider name ----------------------------


def test_frontier_lane_maps_to_frontier_provider(monkeypatch):
    _fresh_settings(
        monkeypatch,
        LANE_FRONTIER_PROVIDER="anthropic",
        LANE_LOCAL_PROVIDER="local",
    )
    assert provider_name_for_lane(LANE_FRONTIER) == "anthropic"


def test_local_lane_maps_to_local_provider(monkeypatch):
    _fresh_settings(
        monkeypatch,
        LANE_FRONTIER_PROVIDER="anthropic",
        LANE_LOCAL_PROVIDER="local",
    )
    assert provider_name_for_lane(LANE_LOCAL) == "local"


def test_unknown_lane_fails_safe_to_local(monkeypatch):
    """Anything that isn't an explicit 'frontier' lane keeps data on-prem."""
    _fresh_settings(
        monkeypatch,
        LANE_FRONTIER_PROVIDER="anthropic",
        LANE_LOCAL_PROVIDER="local",
    )
    assert provider_name_for_lane(None) == "local"
    assert provider_name_for_lane("") == "local"
    assert provider_name_for_lane("garbage") == "local"
    assert provider_name_for_lane("FRONTIER") == "anthropic"  # case-insensitive


# --------------------------- model-for-lane ----------------------------------


def test_model_for_lane_frontier_uses_agent_claude_model(monkeypatch):
    _fresh_settings(monkeypatch, MODEL_DEFAULT="claude-fable-5")
    # a frontier agent pinned to a Claude id keeps it
    assert model_for_lane(LANE_FRONTIER, "claude-sonnet-4-6") == "claude-sonnet-4-6"


def test_model_for_lane_frontier_ignores_stray_local_model(monkeypatch):
    _fresh_settings(monkeypatch, MODEL_DEFAULT="claude-fable-5")
    # a frontier lane must not run an ollama id — fall back to the Claude tier
    assert model_for_lane(LANE_FRONTIER, "ollama:qwen3:14b") == "claude-fable-5"


def test_model_for_lane_local_uses_agent_local_model(monkeypatch):
    _fresh_settings(monkeypatch, MODEL_LOCAL_DEFAULT="ollama:qwen3:14b")
    assert model_for_lane(LANE_LOCAL, "ollama:gemma4:12b-mlx") == "ollama:gemma4:12b-mlx"


def test_model_for_lane_local_ignores_stray_claude_model(monkeypatch):
    """A local-lane agent seeded with a Claude id must NOT try to run it on
    ollama — the lane default (a local id) wins. This is what lets a seeded
    agent be safely re-lane'd to local without editing its model column."""
    _fresh_settings(monkeypatch, MODEL_LOCAL_DEFAULT="ollama:qwen3:14b")
    assert model_for_lane(LANE_LOCAL, "claude-fable-5") == "ollama:qwen3:14b"


# --------------------------- routing gate ------------------------------------


def test_routing_disabled_ignores_lane(monkeypatch):
    """When the flag is off, both lanes resolve to the global MODEL_PROVIDER."""
    _fresh_settings(
        monkeypatch,
        MODEL_LANE_ROUTING_ENABLED="false",
        MODEL_PROVIDER="anthropic",
        LANE_LOCAL_PROVIDER="local",
    )
    # local lane would map to 'local' if routing were on, but it's off →
    # global provider (anthropic) is used regardless of lane.
    assert get_provider_for_lane(LANE_LOCAL).name == "anthropic"
    assert get_provider_for_lane(LANE_FRONTIER).name == "anthropic"


def test_routing_enabled_selects_per_lane(monkeypatch):
    _fresh_settings(
        monkeypatch,
        MODEL_LANE_ROUTING_ENABLED="true",
        MODEL_PROVIDER="anthropic",
        LANE_FRONTIER_PROVIDER="anthropic",
        LANE_LOCAL_PROVIDER="local",
    )
    assert get_provider_for_lane(LANE_FRONTIER).name == "anthropic"
    assert get_provider_for_lane(LANE_LOCAL).name == "local"


def test_routing_enabled_unknown_lane_is_local(monkeypatch):
    _fresh_settings(
        monkeypatch,
        MODEL_LANE_ROUTING_ENABLED="true",
        LANE_LOCAL_PROVIDER="local",
    )
    assert get_provider_for_lane("nonsense").name == "local"


def _reset_cache():
    config_mod.get_settings.cache_clear()


# --------------------------- fail-open wrapper -------------------------------


class _StubProvider:
    """Minimal provider double: either returns a response or raises."""

    def __init__(self, name, *, raise_exc=None, text="ok"):
        self.name = name
        self._raise = raise_exc
        self._text = text
        self.calls = 0
        self.last_model = None

    async def complete(self, *, model, system, messages, tools, max_tokens):
        self.calls += 1
        self.last_model = model
        if self._raise is not None:
            raise self._raise
        return ModelResponse(
            content=[{"type": "text", "text": self._text}],
            stop_reason="end_turn", model=model,
        )


async def test_failopen_uses_local_when_healthy():
    local = _StubProvider("local", text="from-local")
    frontier = _StubProvider("anthropic", text="from-frontier")
    fo = FailOpenProvider(local, frontier, "claude-fable-5")
    resp = await fo.complete(
        model="ollama:qwen3:14b", system="s",
        messages=[{"role": "user", "content": "hi"}], tools=[], max_tokens=64,
    )
    assert resp.text == "from-local"
    assert local.calls == 1 and frontier.calls == 0


async def test_failopen_degrades_to_frontier_when_local_unreachable():
    local = _StubProvider("local", raise_exc=LocalUnreachableError("host down"))
    frontier = _StubProvider("anthropic", text="from-frontier")
    fo = FailOpenProvider(local, frontier, "claude-fable-5")
    resp = await fo.complete(
        model="ollama:qwen3:14b", system="s",
        messages=[{"role": "user", "content": "hi"}], tools=[], max_tokens=64,
    )
    # degraded to frontier, and rewrote the model to the frontier default
    assert resp.text == "from-frontier"
    assert frontier.calls == 1
    assert frontier.last_model == "claude-fable-5"


async def test_failopen_does_not_mask_real_local_errors():
    """A genuine model/API error (NOT unreachable) must NOT fail open — we must
    never retry a bad local request against the cloud."""
    local = _StubProvider("local", raise_exc=ProviderError("bad request 400"))
    frontier = _StubProvider("anthropic")
    fo = FailOpenProvider(local, frontier, "claude-fable-5")
    with pytest.raises(ProviderError):
        await fo.complete(
            model="ollama:qwen3:14b", system="s",
            messages=[{"role": "user", "content": "hi"}], tools=[], max_tokens=64,
        )
    assert frontier.calls == 0  # never leaked to cloud


def test_local_lane_wrapped_when_failopen_enabled(monkeypatch):
    _fresh_settings(
        monkeypatch,
        MODEL_LANE_ROUTING_ENABLED="true",
        MODEL_LANE_FAIL_OPEN="true",
        LANE_LOCAL_PROVIDER="local",
        LANE_FRONTIER_PROVIDER="anthropic",
    )
    prov = get_provider_for_lane(LANE_LOCAL)
    assert isinstance(prov, FailOpenProvider)
    # frontier lane is never wrapped (nothing to fall back to)
    assert not isinstance(get_provider_for_lane(LANE_FRONTIER), FailOpenProvider)
    config_mod.get_settings.cache_clear()


def test_local_lane_not_wrapped_when_failopen_disabled(monkeypatch):
    _fresh_settings(
        monkeypatch,
        MODEL_LANE_ROUTING_ENABLED="true",
        MODEL_LANE_FAIL_OPEN="false",
        LANE_LOCAL_PROVIDER="local",
        LANE_FRONTIER_PROVIDER="anthropic",
    )
    assert not isinstance(get_provider_for_lane(LANE_LOCAL), FailOpenProvider)
    config_mod.get_settings.cache_clear()
