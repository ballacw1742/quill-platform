"""§9.5 electricity-only pricing: local models meter at ~$0."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.providers import pricing as pricing_mod
from app.providers.pricing import cost_usd


def test_canonical_local_model_is_free():
    pricing_mod.pricing_table.cache_clear()
    assert cost_usd("local", 1_000_000, 1_000_000) == 0.0


def test_local_prefix_is_free_regardless_of_provider():
    pricing_mod.pricing_table.cache_clear()
    assert cost_usd("local:gemma4:12b-mlx", 5_000_000, 5_000_000) == 0.0
    assert cost_usd("ollama:qwen3:14b", 1_000_000, 0) == 0.0


def test_local_provider_makes_any_model_free(monkeypatch):
    # With MODEL_PROVIDER=local, even a bare ollama id (no prefix) meters $0
    # instead of falling through to the conservative cloud fallback.
    get_settings.cache_clear()
    pricing_mod.pricing_table.cache_clear()
    monkeypatch.setenv("MODEL_PROVIDER", "local")
    try:
        assert cost_usd("gemma4:12b-mlx", 10_000_000, 10_000_000) == 0.0
    finally:
        get_settings.cache_clear()
        pricing_mod.pricing_table.cache_clear()


def test_cloud_model_unaffected_when_provider_not_local():
    # Sanity: default provider (anthropic in conftest) still prices haiku.
    get_settings.cache_clear()
    pricing_mod.pricing_table.cache_clear()
    assert cost_usd("claude-haiku-4-5", 1_000_000, 0) == 1.0
