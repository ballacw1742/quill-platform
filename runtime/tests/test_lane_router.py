from __future__ import annotations

import pytest

from runtime.lane_router import route_lane


def test_tier0_clean_output_is_lane2():
    d = route_lane(
        output={"confidence": 0.95},
        trust_tier_default="tier-0-mandatory",
    )
    assert d.lane == 2
    assert d.tier == "tier-0-mandatory"


def test_tier2_auto_clean_output_is_lane1():
    d = route_lane(
        output={"confidence": 0.95},
        trust_tier_default="tier-2-auto",
    )
    assert d.lane == 1
    assert d.tier == "tier-2-auto"


def test_charles_approves_alias_is_lane2():
    d = route_lane(
        output={"confidence": 0.95},
        trust_tier_default="tier-2-charles-approves",
    )
    assert d.lane == 2


def test_low_confidence_forces_tier0_lane2_from_auto():
    d = route_lane(
        output={"confidence": 0.5},
        trust_tier_default="tier-2-auto",
    )
    assert d.tier == "tier-0-mandatory"
    assert d.lane == 2
    assert any("low_confidence" in r for r in d.reasons)


def test_cost_impact_forces_tier0():
    d = route_lane(
        output={"confidence": 0.99, "cost_impact_flag": True},
        trust_tier_default="tier-2-auto",
    )
    assert d.tier == "tier-0-mandatory"
    assert d.lane == 2
    assert "cost_impact" in d.reasons


def test_safety_plus_cost_escalates_to_dual_lane3():
    d = route_lane(
        output={"confidence": 0.99, "safety_flag": True, "cost_impact_flag": True},
        trust_tier_default="tier-2-auto",
    )
    assert d.lane == 3
    assert "dual_approval_required" in d.reasons


def test_safety_alone_stays_lane2():
    d = route_lane(
        output={"confidence": 0.99, "safety_flag": True},
        trust_tier_default="tier-2-auto",
    )
    assert d.lane == 2
    assert "safety" in d.reasons


def test_required_approvers_dual_forces_lane3():
    d = route_lane(
        output={"confidence": 0.99},
        trust_tier_default="tier-0-mandatory",
        required_approvers=["owner", "partner"],
    )
    assert d.lane == 3


def test_schedule_impact_critical_path_forces_tier0():
    d = route_lane(
        output={
            "confidence": 0.95,
            "schedule_impact_flag": True,
            "on_critical_path": True,
        },
        trust_tier_default="tier-2-auto",
    )
    assert d.tier == "tier-0-mandatory"
    assert d.lane == 2


def test_schedule_impact_non_critical_is_spotcheck():
    d = route_lane(
        output={"confidence": 0.95, "schedule_impact_flag": True},
        trust_tier_default="tier-2-auto",
    )
    assert d.tier == "tier-1-spotcheck"
    assert d.lane == 2


@pytest.mark.parametrize(
    "default_tier, expected_lane",
    [
        ("tier-2-auto", 1),
        ("tier-1-spotcheck", 2),
        ("tier-0-mandatory", 2),
        ("tier-2-charles-approves", 2),
    ],
)
def test_default_tier_lane_mapping(default_tier, expected_lane):
    d = route_lane(
        output={"confidence": 0.99},
        trust_tier_default=default_tier,
    )
    assert d.lane == expected_lane
