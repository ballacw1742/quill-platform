"""TrustTier promotion state machine (Phase 1c, GAP_ASSESSMENT_S9 §9.4).

Auto-promotes an agent's trust tier on a clean track record:

    tier-0-mandatory  --(N0 clean)-->  tier-1-spotcheck  --(N1 clean)-->  tier-2-auto

Promotion is monotonic (never auto-demotes here — demotion is an explicit admin
action / future incident-response path). A higher tier only makes *low-risk*
writes Lane-1 eligible; money/contract/irreversible writes always stay Lane 2/3
regardless of tier (enforced by app.services.lane_policy, belt #2). So promotion
can never, by itself, let a material write auto-execute.

"Clean track record" is defined explicitly and auditably:

  * A proposal counts toward the streak only if its most recent human decision
    was a plain APPROVE (NOT edit_then_approve, NOT reject/escalate) AND, for
    the tier-1 -> tier-2 step, it also executed successfully.
  * The streak is CONSECUTIVE from the most recent decision backward. Any
    reject, edit_then_approve, or execution_failed breaks the streak and resets
    the count to zero.

Every promotion writes an `agent.trust_promoted` audit event (hash-chained) so
the decision is disputable/replayable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ApprovalStatus, Decision, TrustTier
from app.models import AgentRegistration, ApprovalItem, ApprovalRecord
from app.services import audit as audit_svc

log = logging.getLogger("quill.trust_promotion")

# Promotion thresholds — consecutive clean proposals required for each step.
# Deliberately conservative; tune via ops experience, not per-agent.
PROMOTE_T0_TO_T1 = 10
PROMOTE_T1_TO_T2 = 25

# Ordered tiers (promotion walks forward through this list).
_TIER_ORDER = (
    TrustTier.TIER_0.value,
    TrustTier.TIER_1.value,
    TrustTier.TIER_2.value,
)

# Terminal decisions that a "clean" proposal must be. edit_then_approve is
# intentionally excluded: an edit means the agent's proposal was not correct
# as-submitted, which is exactly what disqualifies auto-execute trust.
_CLEAN_DECISIONS = frozenset({Decision.APPROVE.value})
_BREAKING_DECISIONS = frozenset(
    {Decision.REJECT.value, Decision.EDIT_THEN_APPROVE.value, Decision.ESCALATE.value}
)


@dataclass(frozen=True)
class PromotionResult:
    agent_id: str
    promoted: bool
    from_tier: str
    to_tier: str
    clean_streak: int
    reason: str


def _next_tier(current: str) -> str | None:
    try:
        idx = _TIER_ORDER.index(current)
    except ValueError:
        return None
    if idx >= len(_TIER_ORDER) - 1:
        return None
    return _TIER_ORDER[idx + 1]


def _threshold_for(current: str) -> int | None:
    if current == TrustTier.TIER_0.value:
        return PROMOTE_T0_TO_T1
    if current == TrustTier.TIER_1.value:
        return PROMOTE_T1_TO_T2
    return None  # tier-2 is terminal


async def compute_clean_streak(
    session: AsyncSession, agent_id: str, *, require_executed: bool
) -> int:
    """Count consecutive clean proposals from most-recent decision backward.

    A proposal is represented by its latest ApprovalRecord (human decision).
    We walk decided items for this agent newest-first; a breaking decision or
    (when require_executed) a non-executed terminal item stops the count.
    """
    # Most-recent-first list of this agent's items that have been decided.
    stmt = (
        select(ApprovalItem)
        .where(ApprovalItem.agent_id == agent_id)
        .order_by(ApprovalItem.created_at.desc())
    )
    items = list((await session.execute(stmt)).scalars().all())

    streak = 0
    for item in items:
        # Load the decisions for this item (latest wins).
        recs = list(
            (
                await session.execute(
                    select(ApprovalRecord)
                    .where(ApprovalRecord.approval_item_id == item.id)
                    .order_by(ApprovalRecord.created_at.desc())
                )
            ).scalars().all()
        )
        if not recs:
            # Undecided / auto-executed-without-record item: skip (not evidence
            # of human-approved trust either way) unless it's still pending,
            # which also does not break a streak.
            if item.status == ApprovalStatus.PENDING.value:
                continue
            # A Lane-1 auto-executed item has no human record; it is neutral.
            if item.status == ApprovalStatus.EXECUTED.value:
                continue
            if item.status == ApprovalStatus.EXECUTION_FAILED.value:
                break  # a failure breaks the streak
            continue

        latest = recs[0]
        if latest.decision in _BREAKING_DECISIONS:
            break
        if latest.decision not in _CLEAN_DECISIONS:
            # Unknown decision — be conservative, stop counting.
            break
        if require_executed and item.status != ApprovalStatus.EXECUTED.value:
            # Approved but not (yet) executed successfully — do not count, and
            # if it outright failed, break.
            if item.status == ApprovalStatus.EXECUTION_FAILED.value:
                break
            continue
        streak += 1

    return streak


async def evaluate_promotion(
    session: AsyncSession, agent_id: str, *, actor: str = "system:trust_promotion"
) -> PromotionResult:
    """Evaluate (and apply, if earned) a single-step promotion for one agent.

    Idempotent per call: promotes at most one tier step. Call again to walk
    further. Writes an audit event on promotion. Does NOT commit — the caller
    owns the transaction boundary.
    """
    reg = await session.get(AgentRegistration, agent_id)
    if reg is None:
        return PromotionResult(agent_id, False, "", "", 0, "agent_not_registered")
    if not reg.enabled:
        return PromotionResult(
            agent_id, False, reg.trust_tier, reg.trust_tier, 0, "agent_disabled"
        )

    current = reg.trust_tier
    target = _next_tier(current)
    threshold = _threshold_for(current)
    if target is None or threshold is None:
        return PromotionResult(
            agent_id, False, current, current, 0, "already_max_tier"
        )

    # tier-1 -> tier-2 requires successful execution history (stricter).
    require_executed = current == TrustTier.TIER_1.value
    streak = await compute_clean_streak(
        session, agent_id, require_executed=require_executed
    )

    if streak < threshold:
        return PromotionResult(
            agent_id, False, current, target, streak, f"streak {streak}<{threshold}"
        )

    # Promote.
    reg.trust_tier = target
    # Keep default_lane coherent: a tier-2 agent's default lane becomes AUTO(1);
    # lower tiers stay SINGLE(2). Lane_policy still floors per-action risk.
    from app.enums import Lane

    reg.default_lane = (
        Lane.AUTO.value if target == TrustTier.TIER_2.value else Lane.SINGLE.value
    )

    await audit_svc.record_event_with_mirror(
        session,
        event_type="agent.trust_promoted",
        actor=actor,
        approval_item_id=None,
        payload={
            "agent_id": agent_id,
            "from_tier": current,
            "to_tier": target,
            "clean_streak": streak,
            "threshold": threshold,
            "require_executed": require_executed,
            "new_default_lane": reg.default_lane,
        },
    )
    log.info(
        "trust promoted agent=%s %s->%s (streak=%d)",
        agent_id,
        current,
        target,
        streak,
    )
    return PromotionResult(
        agent_id, True, current, target, streak, "promoted"
    )


async def evaluate_all(
    session: AsyncSession, *, actor: str = "system:trust_promotion"
) -> list[PromotionResult]:
    """Evaluate every enabled registered agent for a one-step promotion.

    Intended to be driven by an operator action or a low-frequency scheduled
    sweep (event-driven where possible; this is the batch belt). Commits once.
    """
    regs = list(
        (
            await session.execute(
                select(AgentRegistration).where(AgentRegistration.enabled.is_(True))
            )
        ).scalars().all()
    )
    results: list[PromotionResult] = []
    for reg in regs:
        results.append(await evaluate_promotion(session, reg.agent_id, actor=actor))
    await session.commit()
    return results


def as_dict(result: PromotionResult) -> dict[str, Any]:
    return {
        "agent_id": result.agent_id,
        "promoted": result.promoted,
        "from_tier": result.from_tier,
        "to_tier": result.to_tier,
        "clean_streak": result.clean_streak,
        "reason": result.reason,
    }
