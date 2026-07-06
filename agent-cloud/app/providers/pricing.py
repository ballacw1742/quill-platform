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
}

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
    # Tolerate versioned ids, e.g. claude-haiku-4-5@20251001 (Vertex style).
    base = model.split("@", 1)[0]
    if base in table:
        return table[base]
    log.warning("no pricing for model %s — using conservative fallback", model)
    return FALLBACK


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = _lookup(model)
    return (input_tokens * p_in + output_tokens * p_out) / 1_000_000.0
