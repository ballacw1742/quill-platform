"""Lane router — implements the trust-tier × materiality rules.

Per `agentic-pmo-prompts/docs/INTEGRATION.md` §2 and Doc 03 of the Quill v2 spec:

```
final_lane = max(
    agent.trust_tier_default,
    tier_for_low_confidence(output.confidence),
    tier_for_cost_or_schedule_impact(output),
    tier_for_safety_flag(output)
)
```

Where the strictness order is `tier-2-auto < tier-1-spotcheck < tier-0-mandatory`.

We then map tiers to wire-level Lane integers (per `app.enums.Lane`):

- tier-2-auto      → Lane 1 (AUTO)
- tier-1-spotcheck → Lane 2 (SINGLE — Charles approves on a spot-check basis)
- tier-2-charles-approves → Lane 2 (SINGLE — alias used by Phase-1 prompts)
- tier-0-mandatory → Lane 2 (SINGLE) by default, escalating to Lane 3 (DUAL) when:
  - `safety_flag` is true AND any of (`cost_impact_flag`, `schedule_impact_flag`) is true, OR
  - `required_approvers` already lists more than one approver (e.g. partner), OR
  - the input explicitly asks for dual review (`requires_dual_approval=true`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# Strictness ranking: higher number = stricter.
_TIER_STRICTNESS: dict[str, int] = {
    "tier-2-auto": 0,
    "tier-1-spotcheck": 1,
    # "Charles approves" is treated as Lane-2 single-approver per prompts repo
    "tier-2-charles-approves": 1,
    "tier-0-mandatory": 2,
}

# Default tier when an unrecognized string shows up — be conservative.
_DEFAULT_UNKNOWN_TIER = "tier-0-mandatory"

LOW_CONFIDENCE_THRESHOLD = 0.70


@dataclass(frozen=True)
class LaneDecision:
    lane: int
    tier: str
    reasons: tuple[str, ...]
    confidence: float
    cost_impact_flag: bool
    schedule_impact_flag: bool
    safety_flag: bool


def _tier_strictness(t: str) -> int:
    return _TIER_STRICTNESS.get(t, _TIER_STRICTNESS[_DEFAULT_UNKNOWN_TIER])


def _strictest(tiers: Iterable[str]) -> str:
    best = "tier-2-auto"
    best_rank = -1
    for t in tiers:
        r = _tier_strictness(t)
        if r > best_rank:
            best = t
            best_rank = r
    return best


def _coerce_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"true", "1", "yes", "y"}
    return bool(v)


def _coerce_float(v: Any, default: float = 1.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def route_lane(
    *,
    output: dict[str, Any],
    trust_tier_default: str,
    required_approvers: list[str] | None = None,
) -> LaneDecision:
    """Pick the wire-level lane for a given agent output."""
    confidence = _coerce_float(output.get("confidence", 1.0), default=1.0)
    cost = _coerce_bool(output.get("cost_impact_flag", False)) or _coerce_bool(
        output.get("requires_change_order", False)
    )
    schedule = _coerce_bool(output.get("schedule_impact_flag", False))
    # The schedule-reader / critical-path agents may emit a more granular signal
    on_critical_path = _coerce_bool(output.get("on_critical_path", False))
    safety = _coerce_bool(output.get("safety_flag", False))
    requires_dual = _coerce_bool(output.get("requires_dual_approval", False))

    reasons: list[str] = []
    candidate_tiers = [trust_tier_default]

    if confidence < LOW_CONFIDENCE_THRESHOLD:
        candidate_tiers.append("tier-0-mandatory")
        reasons.append(f"low_confidence({confidence:.2f}<{LOW_CONFIDENCE_THRESHOLD})")
    if cost:
        candidate_tiers.append("tier-0-mandatory")
        reasons.append("cost_impact")
    if schedule and on_critical_path:
        candidate_tiers.append("tier-0-mandatory")
        reasons.append("schedule_impact_critical_path")
    elif schedule:
        # Non-critical-path schedule impact stays at agent default but escalates spot-check
        candidate_tiers.append("tier-1-spotcheck")
        reasons.append("schedule_impact")
    if safety:
        candidate_tiers.append("tier-0-mandatory")
        reasons.append("safety")

    final_tier = _strictest(candidate_tiers)

    # Tier → lane mapping
    if final_tier == "tier-2-auto":
        lane = 1
    elif final_tier in ("tier-1-spotcheck", "tier-2-charles-approves"):
        lane = 2
    else:  # tier-0-mandatory or unknown
        lane = 2

    # Dual-approval escalation
    approvers = list(required_approvers or [])
    if (
        requires_dual
        or (safety and (cost or schedule))
        or len({a.lower() for a in approvers if a}) > 1
    ):
        lane = 3
        reasons.append("dual_approval_required")

    return LaneDecision(
        lane=lane,
        tier=final_tier,
        reasons=tuple(reasons) if reasons else ("default",),
        confidence=confidence,
        cost_impact_flag=cost,
        schedule_impact_flag=schedule,
        safety_flag=safety,
    )


__all__ = ["LaneDecision", "route_lane", "LOW_CONFIDENCE_THRESHOLD"]
