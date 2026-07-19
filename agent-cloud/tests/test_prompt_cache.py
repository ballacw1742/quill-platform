"""Prompt-caching: system + tools get cache_control breakpoints, cost is
cache-aware, and everything is gated by PROMPT_CACHE_ENABLED.

Caching must NOT change model output — it only marks the stable prefix
(system prompt + tool defs) so Anthropic bills its reuse at ~10%.
"""

import importlib

from app.providers import anthropic_direct as ad
from app.providers.pricing import cost_usd


def _reset_cache_flag(monkeypatch, value: bool):
    # _cache_enabled reads settings live via get_settings(); patch the flag.
    from app import config

    settings = config.get_settings()
    monkeypatch.setattr(settings, "PROMPT_CACHE_ENABLED", value, raising=False)


def test_cached_system_wraps_in_block(monkeypatch):
    _reset_cache_flag(monkeypatch, True)
    out = ad._cached_system("You are a helpful PMO agent.")
    assert isinstance(out, list) and len(out) == 1
    assert out[0]["type"] == "text"
    assert out[0]["text"] == "You are a helpful PMO agent."
    assert out[0]["cache_control"] == {"type": "ephemeral"}


def test_cached_system_passthrough_when_disabled(monkeypatch):
    _reset_cache_flag(monkeypatch, False)
    assert ad._cached_system("sys") == "sys"


def test_cached_system_passthrough_when_empty(monkeypatch):
    _reset_cache_flag(monkeypatch, True)
    assert ad._cached_system("") == ""
    assert ad._cached_system("   ") == "   "


def test_cached_tools_marks_only_last(monkeypatch):
    _reset_cache_flag(monkeypatch, True)
    tools = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    out = ad._cached_tools(tools)
    assert "cache_control" not in out[0]
    assert "cache_control" not in out[1]
    assert out[2]["cache_control"] == {"type": "ephemeral"}
    # original list not mutated
    assert "cache_control" not in tools[2]


def test_cached_tools_passthrough_when_disabled(monkeypatch):
    _reset_cache_flag(monkeypatch, False)
    tools = [{"name": "a"}]
    assert ad._cached_tools(tools) == tools


def test_cached_tools_empty(monkeypatch):
    _reset_cache_flag(monkeypatch, True)
    assert ad._cached_tools([]) == []


def test_cost_usd_cache_aware_cheaper_than_uncached():
    model = "claude-sonnet-4-6"
    # 10k tokens all uncached vs 9k cached-read + 1k fresh
    uncached = cost_usd(model, 10_000, 500)
    cached = cost_usd(model, 1_000, 500, cache_read_input_tokens=9_000)
    assert cached < uncached  # cache reads are ~10% of input cost


def test_cost_usd_backward_compatible():
    """Old 3-arg call still works (cache buckets default 0)."""
    model = "claude-sonnet-4-6"
    base = cost_usd(model, 1000, 200)
    explicit = cost_usd(model, 1000, 200, 0, 0)
    assert base == explicit
