"""Regression: every journey-step intent (web/lib/journey.ts) must resolve to a
real deliverable generator + ADK agent, so submitting a journey step produces
the intended artifact instead of falling through classify_intent()."""

from __future__ import annotations

from app.deliverable_registry import INTENT_TO_DELIVERABLE
from app.routes.requests import INTENT_TO_ADK_AGENT, INTENT_TO_MODULE

# The 12 journey intents that were previously dead (audit 2026-07-20).
JOURNEY_INTENTS = [
    "cost_takeoff",
    "estimate_package",
    "contract_draft",
    "contract_review",
    "contract_execute",
    "change_order",
    "schedule_build",
    "rfi_management",
    "progress_report",
    "commissioning",
    "owner_reporting",
    "operations_status",
]


def test_all_journey_intents_have_a_generator():
    missing = [i for i in JOURNEY_INTENTS if i not in INTENT_TO_DELIVERABLE]
    assert not missing, f"journey intents with no deliverable generator: {missing}"


def test_all_journey_intents_have_an_adk_agent():
    missing = [i for i in JOURNEY_INTENTS if i not in INTENT_TO_ADK_AGENT]
    assert not missing, f"journey intents with no ADK agent: {missing}"


def test_journey_intents_map_to_expected_deliverable_types():
    expected = {
        "cost_takeoff": "cost_estimate",
        "estimate_package": "cost_estimate",
        "contract_draft": "change_order_package",
        "contract_review": "change_order_package",
        "contract_execute": "change_order_package",
        "change_order": "change_order_package",
        "schedule_build": "schedule_package",
        "rfi_management": "rfi_response",
        "progress_report": "ops_report",
        "commissioning": "ops_report",
        "owner_reporting": "ops_report",
        "operations_status": "ops_report",
    }
    for intent, dtype in expected.items():
        assert INTENT_TO_DELIVERABLE[intent].deliverable_type == dtype, intent


def test_journey_intents_are_module_gated():
    # Each journey intent maps to an owning module so the enable/disable gate
    # works (None would mean never gated — acceptable, but we set them).
    for i in JOURNEY_INTENTS:
        assert INTENT_TO_MODULE.get(i) is not None, i
