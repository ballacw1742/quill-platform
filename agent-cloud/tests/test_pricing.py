from app.providers.pricing import cost_usd


def test_haiku_pricing():
    # 1M in @ $1 + 1M out @ $5
    assert cost_usd("claude-haiku-4-5", 1_000_000, 1_000_000) == 6.0


def test_versioned_model_id_falls_back_to_base():
    assert cost_usd("claude-haiku-4-5@20251001", 1_000_000, 0) == 1.0


def test_unknown_model_uses_conservative_fallback():
    # fallback (5, 25) — must never under-count
    assert cost_usd("mystery-model", 1_000_000, 0) == 5.0


def test_zero_tokens_zero_cost():
    assert cost_usd("claude-fable-5", 0, 0) == 0.0
