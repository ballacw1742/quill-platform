"""Chain data-overlay tests (ADK_AGENTS_DESIGN.md §4).

An APPROVED workflow_assignment overrides which agent runs at a stage; an
unapproved assignment is inert (never reaches the overlay map). These tests
prove the overlay function honors approved overrides and appends inserts,
and that an empty overlay is a no-op (pure base-chain behavior).
"""

from __future__ import annotations

from runtime.chains import (
    RFI_CHAIN,
    apply_overlay,
    chain_for_event,
    resolve_chain,
    stage_keys,
)


def test_stage_keys_are_step_agent_ids():
    assert stage_keys(RFI_CHAIN) == ["rfi-triage", "rfi-drafter"]


def test_empty_overlay_is_noop():
    out = apply_overlay(RFI_CHAIN, {})
    assert out is RFI_CHAIN  # returns the same object
    out2 = resolve_chain("rfi.new", overlay={})
    assert out2 is RFI_CHAIN


def test_approved_overlay_overrides_stage_agent():
    overlay = {("rfi.full_triage", "rfi-drafter"): "custom-adk-drafter"}
    out = apply_overlay(RFI_CHAIN, overlay)
    assert stage_keys(out) == ["rfi-triage", "custom-adk-drafter"]
    # The overridden step keeps the base step's gate/composer identity;
    # only the agent_id changes. The first (unrelated) step is untouched.
    assert out.steps[0].agent_id == "rfi-triage"
    assert out.steps[0].gate is RFI_CHAIN.steps[0].gate


def test_overlay_for_other_chain_is_ignored():
    overlay = {("some.other.chain", "rfi-drafter"): "x"}
    out = apply_overlay(RFI_CHAIN, overlay)
    assert stage_keys(out) == stage_keys(RFI_CHAIN)


def test_overlay_insert_appends_new_stage():
    overlay = {("rfi.full_triage", "post-review"): "reviewer-adk"}
    out = apply_overlay(RFI_CHAIN, overlay)
    assert stage_keys(out) == ["rfi-triage", "rfi-drafter", "reviewer-adk"]


def test_resolve_chain_applies_overlay():
    overlay = {("rfi.full_triage", "rfi-triage"): "adk-triage"}
    out = resolve_chain("rfi.created", overlay=overlay)
    assert out is not None
    assert stage_keys(out) == ["adk-triage", "rfi-drafter"]


def test_resolve_chain_unknown_event_none():
    assert resolve_chain("nope.nope", overlay={}) is None
    assert chain_for_event("nope.nope") is None
