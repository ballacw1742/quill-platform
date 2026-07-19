"""Token pricing table (USD per million tokens: [input, output]).

Anthropic-direct == Vertex list pricing (parity, SPIKE_FINDINGS.md), so one
table serves both providers. Override any entry via PRICING_JSON env, e.g.
PRICING_JSON='{"claude-fable-5": [5.0, 25.0]}'.

Unknown models fall back to the most expensive known tier (conservative:
metering must never *under*-count toward a budget cap).
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

from app.config import get_settings

log = logging.getLogger("agentcloud.pricing")

# USD per MTok (input, output).
DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "claude-fable-5": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    # §9.5 local-first: on-prem inference is electricity-only, so budgets /
    # meters read ~0. "local" is the canonical id; any model routed through
    # MODEL_PROVIDER=local or named with the "local:" / "ollama:" prefix is
    # also treated as $0 (see _lookup) so a user's real ollama model id
    # (e.g. "gemma4:12b-mlx") does not fall through to the conservative
    # cloud fallback and inflate a local budget.
    "local": (0.0, 0.0),
}

# Providers whose token cost is electricity-only (§9.5). When the active
# MODEL_PROVIDER is one of these, every model meters at $0.
ZERO_COST_PROVIDERS = frozenset({"local"})

# Model-id prefixes that always price at $0 regardless of provider, so a
# local model id can be pinned to free even in a mixed deployment.
ZERO_COST_PREFIXES = ("local:", "ollama:")

# Conservative fallback for unknown models.
FALLBACK = (5.0, 25.0)


@lru_cache
def pricing_table() -> dict[str, tuple[float, float]]:
    table = dict(DEFAULT_PRICING)
    raw = get_settings().PRICING_JSON
    if raw:
        try:
            for model, pair in json.loads(raw).items():
                table[model] = (float(pair[0]), float(pair[1]))
        except (ValueError, TypeError, IndexError) as exc:
            log.error("invalid PRICING_JSON ignored: %s", exc)
    return table


def _lookup(model: str) -> tuple[float, float]:
    table = pricing_table()
    if model in table:
        return table[model]
    # §9.5: any local model prices at $0. Two triggers, either sufficient:
    #  (a) the active provider is electricity-only (MODEL_PROVIDER=local), or
    #  (b) the model id is explicitly prefixed local:/ollama:.
    # A PRICING_JSON override for the exact id still wins (checked above).
    lowered = model.lower()
    if lowered.startswith(ZERO_COST_PREFIXES):
        return (0.0, 0.0)
    if get_settings().MODEL_PROVIDER.strip().lower() in ZERO_COST_PROVIDERS:
        return (0.0, 0.0)
    # Tolerate versioned ids, e.g. claude-haiku-4-5@20251001 (Vertex style).
    base = model.split("@", 1)[0]
    if base in table:
        return table[base]
    log.warning("no pricing for model %s — using conservative fallback", model)
    return FALLBACK


# Anthropic prompt-caching multipliers on the base input rate:
#   cache READ  ≈ 0.1x (90% cheaper on reuse)
#   cache WRITE ≈ 1.25x (one-time 25% surcharge to store, 5-min TTL)
# Applied only to the respective token buckets; regular input_tokens (the
# uncached portion Anthropic reports) are billed at the normal rate.
_CACHE_READ_MULT = 0.1
_CACHE_WRITE_MULT = 1.25


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> float:
    """Cost in USD, cache-aware.

    `input_tokens` is the uncached input Anthropic bills at full rate.
    Cache reads/writes are billed against the same base input rate with the
    multipliers above. Passing 0 for the cache buckets (the default) preserves
    the original non-cached behavior for callers that don't track them.
    """
    p_in, p_out = _lookup(model)
    billable_input = (
        input_tokens
        + cache_read_input_tokens * _CACHE_READ_MULT
        + cache_creation_input_tokens * _CACHE_WRITE_MULT
    )
    return (billable_input * p_in + output_tokens * p_out) / 1_000_000.0
