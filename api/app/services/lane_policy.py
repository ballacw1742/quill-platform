"""Lane-decision policy — api-side belt #2 mirror (Phase 1, GAP §9.4).

Same algorithm as ``agent-cloud/app/lane_policy.py`` (belt #1), vendored on the
api side so the approvals service can INDEPENDENTLY re-derive the lane floor for
an ``agentcloud.*`` proposal from the canonical ``AgentRegistration.trust_tier``
+ the proposed action's risk class — never blindly trusting the lane agent-cloud
sent. If agent-cloud (buggy or compromised) marks a money/contract/irreversible
write as Lane 1, the api floors it back to Lane 2. This is the enforcement point
for Charles's HITL guarantee.

Consults:
  * the agent's trust tier (``AgentRegistration.trust_tier``, canonical),
  * the per-action risk class + arg-derived risk flags, and
  * the shared lane-decision contract (``app/contracts/lane_decision.json``).

Semantics mirror ``runtime.runtime.lane_router.route_lane`` (strictest-wins).
A drift test asserts the lane_decision.json copies are byte-identical.

HARD SAFETY INVARIANT (do not weaken): if any of money / contract /
irreversible is set, the result can NEVER be Lane 1, regardless of trust tier.
``test_lane_policy.py`` proves a tier-2 agent's money/contract/irreversible
write still routes to Lane 2/3.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

# Wire-level lanes (mirror api/app/enums.py::Lane).
LANE_AUTO = 1
LANE_SINGLE = 2
LANE_DUAL = 3

# Flags that make Lane 1 impossible (the HITL floor).
_NEVER_LANE1_FLAGS = frozenset(
    {"money", "contract", "irreversible", "cost_impact", "critical_path", "low_confidence"}
)

# api-side module lives in app/services/; the vendored contract lives in
# app/contracts/ (sibling of services). Byte-identical to the agent-cloud copy;
# a drift test asserts equality.
_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contracts" / "lane_decision.json"


@lru_cache(maxsize=1)
def _contract() -> dict:
    with _CONTRACT_PATH.open() as fh:
        return json.load(fh)


def contract_version() -> int:
    return int(_contract()["contract_version"])


@dataclass(frozen=True)
class LaneDecision:
    lane: int
    trust_tier: str
    action: str
    risk_flags: tuple[str, ...]
    reasons: tuple[str, ...]
    lane1_eligible: bool = False

    def as_audit_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane,
            "trust_tier": self.trust_tier,
            "action": self.action,
            "risk_flags": list(self.risk_flags),
            "reasons": list(self.reasons),
            "lane1_eligible": self.lane1_eligible,
        }


@dataclass
class _RiskContext:
    flags: set[str] = field(default_factory=set)
    reasons: list[str] = field(default_factory=list)


def _normalize_tier(trust_tier: str | None) -> str:
    """Any unrecognized/empty tier collapses to the strictest (never weaken)."""
    valid = set(_contract()["trust_tier_default_lane"])
    if trust_tier in valid:
        return trust_tier
    return "tier-0-mandatory"


def compute_risk_flags(
    action: str,
    args: dict[str, Any],
    *,
    confidence: float | None = None,
) -> tuple[set[str], list[str]]:
    """Derive the risk-flag set for an action + its concrete args.

    Static flags (always apply to the action) + conditional flags (apply when a
    specific arg / arg-value is present) + confidence-derived low_confidence.
    """
    c = _contract()
    ctx = _RiskContext()
    spec = c["actions"].get(action)
    if spec is None:
        # Unknown action → treat as maximally risky (defensive).
        ctx.flags.update({"irreversible", "contract"})
        ctx.reasons.append(f"unknown_action:{action}")
        return ctx.flags, ctx.reasons

    for f in spec.get("static_flags", []):
        ctx.flags.add(f)
        ctx.reasons.append(f"static:{f}")

    conditional = spec.get("conditional_flags", {})
    for key, flags in conditional.items():
        if ":" in key:
            arg_name, expected = key.split(":", 1)
            present = str(args.get(arg_name)) == expected and args.get(arg_name) is not None
        else:
            arg_name = key
            present = args.get(arg_name) is not None
        if present:
            for f in flags:
                ctx.flags.add(f)
                ctx.reasons.append(f"arg[{key}]->{f}")

    if confidence is not None:
        threshold = float(c.get("low_confidence_threshold", 0.70))
        if confidence < threshold:
            ctx.flags.add("low_confidence")
            ctx.reasons.append(f"low_confidence({confidence:.2f}<{threshold})")

    return ctx.flags, ctx.reasons


def decide_lane(
    *,
    trust_tier: str | None,
    action: str,
    args: dict[str, Any],
    confidence: float | None = None,
    requires_dual_approval: bool = False,
) -> LaneDecision:
    """Return the risk-graded lane for a cloud-agent proposal.

    strictest-wins over: agent-default lane, per-action base lane, and any
    escalation implied by a risk flag. Lane 1 is only reachable for a
    lane1_eligible action from a tier-2 agent with zero never-lane1 flags.
    """
    c = _contract()
    tier = _normalize_tier(trust_tier)
    agent_default = int(c["trust_tier_default_lane"][tier])

    spec = c["actions"].get(action, {})
    base_lane = int(spec.get("base_lane", LANE_SINGLE))
    lane1_eligible_action = bool(spec.get("lane1_eligible", False))

    flags, reasons = compute_risk_flags(action, args, confidence=confidence)

    # Start from the strictest of agent-default and per-action base lane.
    lane = max(agent_default, base_lane)
    decision_reasons: list[str] = [
        f"tier={tier}(default_lane={agent_default})",
        f"action={action}(base_lane={base_lane})",
    ]
    decision_reasons.extend(reasons)

    never_lane1 = bool(flags & _NEVER_LANE1_FLAGS)

    # HARD FLOOR: any never-lane1 flag forces at least Lane 2.
    if never_lane1:
        lane = max(lane, LANE_SINGLE)
        blocking = sorted(flags & _NEVER_LANE1_FLAGS)
        decision_reasons.append(f"never_lane1_floor({','.join(blocking)})")

    # Lane 1 is only reachable when the action is eligible, the agent is tier-2,
    # and there are zero never-lane1 flags. Otherwise floor at Lane 2.
    lane1_reachable = (
        lane1_eligible_action and agent_default == LANE_AUTO and not never_lane1
    )
    if lane == LANE_AUTO and not lane1_reachable:
        lane = LANE_SINGLE
        decision_reasons.append("lane1_not_reachable->floor_lane2")

    # Dual-approval escalation.
    dual = False
    if requires_dual_approval:
        dual = True
        decision_reasons.append("explicit_dual_approval")
    if "money" in flags and "critical_path" in flags:
        dual = True
        decision_reasons.append("money+critical_path")
    if "contract" in flags and "cost_impact" in flags:
        dual = True
        decision_reasons.append("contract+cost_impact")
    if dual:
        lane = LANE_DUAL

    return LaneDecision(
        lane=lane,
        trust_tier=tier,
        action=action,
        risk_flags=tuple(sorted(flags)),
        reasons=tuple(decision_reasons),
        lane1_eligible=lane1_reachable,
    )


__all__ = [
    "LaneDecision",
    "decide_lane",
    "compute_risk_flags",
    "contract_version",
    "LANE_AUTO",
    "LANE_SINGLE",
    "LANE_DUAL",
]
