"""Tests for runtime.chains — chain runner with mocked agents."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from runtime.agent import AgentRun
from runtime.chains import (
    Chain,
    ChainResult,
    Step,
    chain_for_event,
    confidence_gate,
    DEFAULT_CHAINS,
    RFI_CHAIN,
    SUBMITTAL_CHAIN,
    run_chain,
)
from runtime.lane_router import LaneDecision


def _make_run(
    *,
    agent_id: str,
    output: dict[str, Any] | None,
    confidence: float = 0.9,
    lane: int = 2,
    validation_ok: bool = True,
    error: str | None = None,
) -> AgentRun:
    decision = LaneDecision(
        lane=lane,
        tier="tier-0-mandatory",
        reasons=["test"],
        confidence=confidence,
        cost_impact_flag=False,
        schedule_impact_flag=False,
        safety_flag=False,
    ) if output is not None and validation_ok else None
    return AgentRun(
        agent_id=agent_id,
        agent_version="0.1.0",
        prompt_version_hash="0" * 64,
        model_used="claude-test",
        input_payload={},
        input_hash="ih",
        output=output,
        output_hash="oh" if output else None,
        raw_text="",
        validation_ok=validation_ok,
        validation_errors=[],
        lane_decision=decision,
        latency_ms=10,
        tokens_used={"input": 1, "output": 1},
        fell_back=False,
        error=error,
    )


def _mock_agent_factory(runs_by_agent: dict[str, AgentRun]):
    """Returns a factory that yields a MagicMock with .run() returning the
    AgentRun keyed by agent_id."""

    def _factory(agent_id: str) -> Any:
        agent = MagicMock()
        agent.agent_id = agent_id
        agent.run = AsyncMock(return_value=runs_by_agent[agent_id])
        return agent

    return _factory


# ---------------------------------------------------------------------------
# confidence_gate
# ---------------------------------------------------------------------------
def test_confidence_gate_allows_above_threshold():
    gate = confidence_gate(0.7)
    run = _make_run(agent_id="a", output={"confidence": 0.85}, confidence=0.85)
    ctx = MagicMock()
    assert gate(run, ctx) is True


def test_confidence_gate_blocks_below_threshold():
    gate = confidence_gate(0.7)
    run = _make_run(agent_id="a", output={"confidence": 0.55}, confidence=0.55)
    ctx = MagicMock()
    assert gate(run, ctx) is False


def test_confidence_gate_blocks_on_escalations():
    gate = confidence_gate(0.7)
    run = _make_run(
        agent_id="a",
        output={"confidence": 0.95, "escalations": ["safety-flag"]},
        confidence=0.95,
    )
    ctx = MagicMock()
    assert gate(run, ctx) is False


def test_confidence_gate_blocks_on_lane_3():
    gate = confidence_gate(0.7)
    run = _make_run(agent_id="a", output={"confidence": 0.95}, confidence=0.95, lane=3)
    ctx = MagicMock()
    assert gate(run, ctx) is False


def test_confidence_gate_blocks_on_invalid_run():
    gate = confidence_gate(0.7)
    run = _make_run(agent_id="a", output=None, validation_ok=False, error="bad")
    ctx = MagicMock()
    assert gate(run, ctx) is False


# ---------------------------------------------------------------------------
# chain_for_event
# ---------------------------------------------------------------------------
def test_chain_for_event_resolves_rfi():
    assert chain_for_event("rfi.new") is RFI_CHAIN
    assert chain_for_event("rfi.created") is RFI_CHAIN


def test_chain_for_event_resolves_submittal():
    assert chain_for_event("submittal.new") is SUBMITTAL_CHAIN


def test_chain_for_event_returns_none_unknown():
    assert chain_for_event("nope.unknown") is None


def test_default_chains_have_unique_ids():
    ids = [c.chain_id for c in DEFAULT_CHAINS]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# run_chain — happy path
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_chain_happy_path_runs_all_steps_and_submits():
    triage_run = _make_run(
        agent_id="rfi-triage",
        output={"confidence": 0.85, "discipline": "structural"},
        confidence=0.85,
    )
    drafter_run = _make_run(
        agent_id="rfi-drafter",
        output={"confidence": 0.92, "draft_markdown": "## Response\nSee S-201."},
        confidence=0.92,
    )

    queue = MagicMock()
    queue.create_approval = AsyncMock(return_value={"id": "appr-chain-1"})

    factory = _mock_agent_factory(
        {"rfi-triage": triage_run, "rfi-drafter": drafter_run}
    )
    result = await run_chain(
        RFI_CHAIN,
        {"rfi_id": "RFI-001", "body": "..."},
        queue_client=queue,
        agent_factory=factory,
    )

    assert isinstance(result, ChainResult)
    assert result.submitted_approval_id == "appr-chain-1"
    assert len(result.runs) == 2
    assert [r.agent_id for r in result.runs] == ["rfi-triage", "rfi-drafter"]
    assert result.errors == []
    assert result.skipped == []
    queue.create_approval.assert_awaited_once()
    submitted = queue.create_approval.await_args.args[0]
    assert submitted["agent_id"] == "rfi-drafter"
    assert "chain_outputs" in submitted["payload"]
    assert submitted["payload"]["chain_outputs"]["chain_id"] == "rfi.full_triage"
    assert len(submitted["payload"]["chain_outputs"]["steps"]) == 2


@pytest.mark.asyncio
async def test_run_chain_gates_drafter_when_low_confidence():
    triage_run = _make_run(
        agent_id="rfi-triage",
        output={"confidence": 0.5, "discipline": "structural"},
        confidence=0.5,
    )
    drafter_run = _make_run(
        agent_id="rfi-drafter",
        output={"confidence": 0.9, "draft_markdown": "..."},
        confidence=0.9,
    )

    queue = MagicMock()
    queue.create_approval = AsyncMock(return_value={"id": "appr-chain-2"})

    factory = _mock_agent_factory(
        {"rfi-triage": triage_run, "rfi-drafter": drafter_run}
    )
    result = await run_chain(
        RFI_CHAIN,
        {"rfi_id": "RFI-002"},
        queue_client=queue,
        agent_factory=factory,
    )

    # Drafter gated out; only triage ran but the queue item is still submitted
    # so Charles sees the classification in the queue.
    assert len(result.runs) == 1
    assert result.runs[0].agent_id == "rfi-triage"
    assert "rfi-drafter" in result.skipped
    assert result.submitted_approval_id == "appr-chain-2"
    submitted = queue.create_approval.await_args.args[0]
    assert submitted["payload"]["chain_outputs"]["skipped"] == ["rfi-drafter"]


@pytest.mark.asyncio
async def test_run_chain_stops_on_step_error_and_does_not_submit():
    bad_run = _make_run(
        agent_id="rfi-triage",
        output=None,
        validation_ok=False,
        error="schema_validation_failed",
    )
    drafter_run = _make_run(
        agent_id="rfi-drafter",
        output={"confidence": 0.9},
        confidence=0.9,
    )
    queue = MagicMock()
    queue.create_approval = AsyncMock()

    factory = _mock_agent_factory(
        {"rfi-triage": bad_run, "rfi-drafter": drafter_run}
    )
    result = await run_chain(
        RFI_CHAIN,
        {"rfi_id": "RFI-003"},
        queue_client=queue,
        agent_factory=factory,
    )

    assert len(result.runs) == 1
    assert result.errors and "schema_validation_failed" in result.errors[0]
    assert result.submitted_approval_id is None
    queue.create_approval.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_chain_handles_submit_error_gracefully():
    triage_run = _make_run(
        agent_id="rfi-triage",
        output={"confidence": 0.85},
        confidence=0.85,
    )
    drafter_run = _make_run(
        agent_id="rfi-drafter",
        output={"confidence": 0.92, "draft_markdown": "ok"},
        confidence=0.92,
    )

    queue = MagicMock()
    queue.create_approval = AsyncMock(side_effect=RuntimeError("API 500"))

    factory = _mock_agent_factory(
        {"rfi-triage": triage_run, "rfi-drafter": drafter_run}
    )
    result = await run_chain(
        RFI_CHAIN,
        {"rfi_id": "RFI-004"},
        queue_client=queue,
        agent_factory=factory,
    )

    assert result.submitted_approval_id is None
    assert any("submit" in e for e in result.errors)
    # Steps still ran:
    assert len(result.runs) == 2


@pytest.mark.asyncio
async def test_run_chain_no_submit_flag():
    triage_run = _make_run(
        agent_id="dfr-synthesizer",
        output={"confidence": 0.95},
        confidence=0.95,
    )
    queue = MagicMock()
    queue.create_approval = AsyncMock()
    factory = _mock_agent_factory({"dfr-synthesizer": triage_run})

    chain = Chain(
        chain_id="dfr.synthesis",
        event_kinds=("dfr.new",),
        steps=(Step("dfr-synthesizer"),),
    )
    result = await run_chain(
        chain,
        {"dfr_id": "DFR-1"},
        queue_client=queue,
        agent_factory=factory,
        submit_combined=False,
    )
    assert result.submitted_approval_id is None
    queue.create_approval.assert_not_awaited()


def test_to_chain_outputs_shape():
    triage_run = _make_run(
        agent_id="rfi-triage",
        output={"confidence": 0.84, "discipline": "structural"},
        confidence=0.84,
    )
    drafter_run = _make_run(
        agent_id="rfi-drafter",
        output={"confidence": 0.91, "draft_markdown": "## Response"},
        confidence=0.91,
    )
    result = ChainResult(
        chain_id="rfi.full_triage",
        runs=[triage_run, drafter_run],
        skipped=[],
        errors=[],
    )
    blob = result.to_chain_outputs()
    assert blob["chain_id"] == "rfi.full_triage"
    assert len(blob["steps"]) == 2
    assert blob["steps"][0]["agent_id"] == "rfi-triage"
    assert blob["steps"][1]["agent_id"] == "rfi-drafter"
    assert blob["steps"][1]["output"]["draft_markdown"].startswith("## Response")
    assert blob["skipped"] == []
    assert blob["errors"] == []
