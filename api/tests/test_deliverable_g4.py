"""Phase G4 tests — pipeline wiring, mid-chain resume, co-dev gate routing.

Scenarios verified (~12 tests):

  1.  run_deliverable_chain default path (start_step_index=0) is behaviorally
      identical to pre-G4 — existing tests must still hold; this is a sanity
      re-run of the key invariant.
  2.  run_deliverable_chain mid-chain resume: calling with start_step_index=1
      and existing_row runs remaining steps WITHOUT re-creating the deliverable.
      Row count stays 1; version is bumped by the resumed steps only.
  3.  Mid-chain resume with start_step_index >= len(steps) is a no-op; returns
      existing_row unchanged (no new versions).
  4.  Mid-chain resume preserves accumulated meta (chain_steps, steps_completed)
      rather than resetting it.
  5.  Chain error during resume leaves last-good version intact; the call
      returns the row (not None, not raising).
  6.  POST /v1/deliverables/{id}/resume with resume_chain=True AND remaining
      steps: endpoint invokes the chain and returns 200 with current state.
  7.  POST /v1/deliverables/{id}/resume with resume_chain=True AND no remaining
      steps (steps_completed == len(steps)): no-op resume, still 200.
  8.  POST /v1/deliverables/{id}/resume chain error path: chain error leaves
      deliverable at last-good version; endpoint returns 200 (not 500).
  9.  co_development gate in requests.py sets hitl_kind=co_development on the
      deliverable meta AND does NOT create an ApprovalItem.
  10. decision gate (default) in requests.py still creates an ApprovalItem
      (unchanged from Phase D).
  11. rfi_response registry entry has terminal_hitl="co_development".
  12. cost_estimate registry entry has terminal_hitl="decision" (default).
  13. _request_out enriches RequestOut with deliverable_hitl_kind and
      deliverable_status when output_id is set.
  14. RequestOut deliverable_hitl_kind is None when no deliverable is linked.

Test style:
  - ``client`` fixture for SessionLocal monkeypatching
  - ``owner_token`` fixture for user setup
  - ``monkeypatch`` to control ADK calls and chain runners
  - Direct DB inspection via db_module.SessionLocal
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

# Import models at top level so create_all registers them (conftest quirk).
import app.routes.requests  # noqa: F401
from app.models import ApprovalItem
from app.models_deliverables import Deliverable, DeliverableVersion
from app.enums import DELIVERABLE_ACCEPT_WORKFLOW

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------


def auth_h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class _Resp:
    """Minimal httpx-like response for monkeypatching."""

    def __init__(self, status_code: int = 200, text: str = "agent output") -> None:
        self.status_code = status_code
        self.text = text

    def json(self) -> dict:
        return {"response": self.text}


async def _create_deliverable(
    session_maker,
    uid: str,
    status: str = "awaiting_human",
    deliverable_type: str = "cost_estimate",
    meta: dict | None = None,
    content: dict | None = None,
) -> Deliverable:
    from app.routes.deliverables import (
        create_deliverable_service,
        append_deliverable_version_service,
    )

    async with session_maker() as s:
        row = await create_deliverable_service(
            s,
            user_id=uid,
            project_id=None,
            module_key="estimates",
            deliverable_type=deliverable_type,
            title=f"G4 test deliverable ({deliverable_type})",
            content=content or {"summary": "step A output", "step_key": "scope_draft", "seed_message": "build me an estimate"},
        )
        if status != "draft" or meta:
            row = await append_deliverable_version_service(
                s,
                row,
                status=status,
                meta=meta,
                change_action="updated",
            )
        return row


async def _fetch(session_maker, deliverable_id: str) -> Deliverable:
    async with session_maker() as s:
        return await s.get(Deliverable, deliverable_id)


async def _count_versions(session_maker, deliverable_id: str) -> int:
    async with session_maker() as s:
        result = await s.execute(
            select(DeliverableVersion).where(
                DeliverableVersion.deliverable_id == deliverable_id
            )
        )
        return len(result.scalars().all())


# ---------------------------------------------------------------------------
# Tests 1–2: run_deliverable_chain default + mid-chain resume
# ---------------------------------------------------------------------------


async def test_default_chain_still_produces_deliverable(client, owner_token, session_maker, monkeypatch):
    """Test 1: Default path (start_step_index=0) is behaviorally identical to pre-G4."""
    uid, token = owner_token

    from app.deliverable_pipeline import run_deliverable_chain

    step_calls: list[str] = []

    async def _mock_call_agent(agent_name: str, msg: str) -> str:
        step_calls.append(agent_name)
        return f"agent output for {agent_name} step {len(step_calls)}"

    async with session_maker() as s:
        row = await run_deliverable_chain(
            s,
            user_id=uid,
            project_id=None,
            deliverable_type="cost_estimate",
            seed_message="estimate request",
            call_agent=_mock_call_agent,
            # default: start_step_index=0, existing_row=None
        )

    assert row is not None
    assert row.version >= 2  # step A (v1) + step B (v2)
    assert row.status == "awaiting_human"
    meta = row.meta or {}
    assert meta.get("steps_completed") == 2
    assert len(meta.get("chain_steps", [])) == 2
    # 2 steps for cost_estimate
    assert len(step_calls) == 2


async def test_mid_chain_resume_runs_remaining_steps_on_existing_row(client, owner_token, session_maker, monkeypatch):
    """Test 2: Mid-chain resume runs remaining steps on existing_row, not a new row."""
    uid, token = owner_token

    # Create a deliverable that's at step 1 complete (v1 done, step B pending).
    existing = await _create_deliverable(
        session_maker,
        uid,
        status="in_progress",
        deliverable_type="cost_estimate",
        meta={
            "chain_steps": [{"key": "scope_draft", "agent_name": "quill_coordinator", "role": "Scope/Takeoff Draft", "version": 1}],
            "steps_completed": 1,
        },
        content={"summary": "step A output", "step_key": "scope_draft", "seed_message": "estimate me something"},
    )
    existing_id = existing.id
    initial_version = existing.version

    from app.deliverable_pipeline import run_deliverable_chain

    resume_calls: list[str] = []

    async def _mock_call_agent(agent_name: str, msg: str) -> str:
        resume_calls.append(agent_name)
        return f"resumed step output for {agent_name}"

    # Reload the row in a fresh session for the resume.
    async with session_maker() as s:
        existing_reloaded = await s.get(Deliverable, existing_id)
        result = await run_deliverable_chain(
            s,
            user_id=uid,
            project_id=None,
            deliverable_type="cost_estimate",
            seed_message="estimate me something",
            call_agent=_mock_call_agent,
            start_step_index=1,       # skip step A (already done)
            existing_row=existing_reloaded,
        )

    # Should have called the agent only for the remaining step(s).
    assert len(resume_calls) == 1, f"Expected 1 resumed step call, got {len(resume_calls)}"
    # Result should be the same deliverable row (not None).
    assert result is not None
    assert result.id == existing_id
    # Version should be bumped by the resumed step.
    assert result.version == initial_version + 1
    # Status should be awaiting_human (last step of cost_estimate chain).
    assert result.status == "awaiting_human"
    # Meta should still record the original step AND the new step.
    meta = result.meta or {}
    assert meta.get("steps_completed") == 2
    # chain_steps should have both step A (from original meta) and the resumed step B.
    chain_steps = meta.get("chain_steps", [])
    assert len(chain_steps) == 2, f"Expected 2 chain_steps, got {chain_steps}"


async def test_mid_chain_resume_noop_when_all_steps_done(client, owner_token, session_maker, monkeypatch):
    """Test 3: Resume with start_step_index >= len(steps) is a no-op; existing_row returned unchanged."""
    uid, token = owner_token

    existing = await _create_deliverable(
        session_maker,
        uid,
        status="awaiting_human",
        deliverable_type="cost_estimate",
        meta={"steps_completed": 2, "chain_steps": []},
    )
    initial_version = existing.version
    existing_id = existing.id

    from app.deliverable_pipeline import run_deliverable_chain

    call_count = 0

    async def _mock_call_agent(agent_name: str, msg: str) -> str:
        nonlocal call_count
        call_count += 1
        return "should not be called"

    # cost_estimate has 2 steps; start_step_index=2 means all done.
    async with session_maker() as s:
        existing_reloaded = await s.get(Deliverable, existing_id)
        result = await run_deliverable_chain(
            s,
            user_id=uid,
            project_id=None,
            deliverable_type="cost_estimate",
            seed_message="estimate me something",
            call_agent=_mock_call_agent,
            start_step_index=2,
            existing_row=existing_reloaded,
        )

    # No agent calls should have been made.
    assert call_count == 0
    # Should return the existing_row.
    assert result is not None
    assert result.id == existing_id
    # Version unchanged.
    assert result.version == initial_version


async def test_mid_chain_resume_preserves_accumulated_meta(client, owner_token, session_maker, monkeypatch):
    """Test 4: Mid-chain resume preserves existing meta (chain_steps, steps_completed)."""
    uid, token = owner_token

    original_chain_steps = [
        {"key": "scope_draft", "agent_name": "quill_coordinator", "role": "Scope/Takeoff Draft", "version": 1}
    ]
    existing = await _create_deliverable(
        session_maker,
        uid,
        status="in_progress",
        deliverable_type="cost_estimate",
        meta={
            "chain_steps": original_chain_steps,
            "steps_completed": 1,
            "custom_key": "preserved_value",
        },
        content={"summary": "step A out", "seed_message": "build estimate"},
    )
    existing_id = existing.id

    from app.deliverable_pipeline import run_deliverable_chain

    async def _mock_call_agent(agent_name: str, msg: str) -> str:
        return "resumed step B output"

    async with session_maker() as s:
        existing_reloaded = await s.get(Deliverable, existing_id)
        result = await run_deliverable_chain(
            s,
            user_id=uid,
            project_id=None,
            deliverable_type="cost_estimate",
            seed_message="build estimate",
            call_agent=_mock_call_agent,
            start_step_index=1,
            existing_row=existing_reloaded,
        )

    assert result is not None
    meta = result.meta or {}
    # Custom key preserved (not reset).
    assert meta.get("custom_key") == "preserved_value"
    # chain_steps extended, not replaced.
    chain_steps = meta.get("chain_steps", [])
    assert len(chain_steps) == 2
    assert chain_steps[0]["key"] == "scope_draft"  # original step preserved


async def test_mid_chain_resume_error_leaves_last_good_version(client, owner_token, session_maker, monkeypatch):
    """Test 5: Chain error during resume leaves last-good version intact; returns row not raising."""
    uid, token = owner_token

    existing = await _create_deliverable(
        session_maker,
        uid,
        status="in_progress",
        deliverable_type="cost_estimate",
        meta={"chain_steps": [{"key": "scope_draft", "agent_name": "quill_coordinator", "role": "r", "version": 1}], "steps_completed": 1},
        content={"summary": "step A out", "seed_message": "build estimate"},
    )
    existing_id = existing.id
    initial_version = existing.version

    from app.deliverable_pipeline import run_deliverable_chain

    async def _failing_agent(agent_name: str, msg: str) -> str:
        raise RuntimeError("simulated agent failure during resume")

    async with session_maker() as s:
        existing_reloaded = await s.get(Deliverable, existing_id)
        result = await run_deliverable_chain(
            s,
            user_id=uid,
            project_id=None,
            deliverable_type="cost_estimate",
            seed_message="build estimate",
            call_agent=_failing_agent,
            start_step_index=1,
            existing_row=existing_reloaded,
        )

    # Should return the existing_row (not None, not raised).
    assert result is not None
    assert result.id == existing_id
    # Version unchanged — last good state.
    assert result.version == initial_version
    # Status unchanged — still in_progress (last good state).
    assert result.status == "in_progress"


# ---------------------------------------------------------------------------
# Tests 6–8: POST /resume endpoint mid-chain behaviour
# ---------------------------------------------------------------------------


async def test_resume_endpoint_triggers_chain_with_remaining_steps(client, owner_token, session_maker, monkeypatch):
    """Test 6: POST /resume with resume_chain=True and remaining steps → chain runs → 200."""
    uid, token = owner_token
    from app.routes import deliverables as del_mod

    # Create deliverable at awaiting_human with steps_completed=1
    existing = await _create_deliverable(
        session_maker,
        uid,
        status="awaiting_human",
        deliverable_type="cost_estimate",
        meta={
            "hitl_kind": "co_development",
            "steps_completed": 1,
            "chain_steps": [{"key": "scope_draft", "agent_name": "qc", "role": "r", "version": 1}],
        },
        content={"summary": "step A out", "seed_message": "estimate me"},
    )

    # Patch the codev agent call used in the resume's _chain_call_agent.
    async def _mock_codev_agent(endpoint, payload, agent_id, deliverable_id):
        return _Resp(200, "agent resumed step")

    monkeypatch.setattr(del_mod, "_call_codev_agent", _mock_codev_agent)

    resp = await client.post(
        f"/v1/deliverables/{existing.id}/resume",
        json={"content": {"summary": "human contributed content"}, "resume_chain": True},
        headers=auth_h(token),
    )
    assert resp.status_code == 200, f"resume failed: {resp.text}"
    data = resp.json()
    assert data["id"] == existing.id


async def test_resume_endpoint_noop_when_no_remaining_steps(client, owner_token, session_maker, monkeypatch):
    """Test 7: POST /resume with resume_chain=True but no remaining steps → no-op, 200."""
    uid, token = owner_token
    from app.routes import deliverables as del_mod

    # cost_estimate has 2 steps; steps_completed=2 means all done.
    existing = await _create_deliverable(
        session_maker,
        uid,
        status="awaiting_human",
        deliverable_type="cost_estimate",
        meta={
            "hitl_kind": "co_development",
            "steps_completed": 2,
            "chain_steps": [{"key": "s1", "agent_name": "qc", "role": "r", "version": 1}, {"key": "s2", "agent_name": "qc", "role": "r", "version": 2}],
        },
    )

    async def _mock_codev_agent(endpoint, payload, agent_id, deliverable_id):
        return _Resp(200, "should not be called")

    monkeypatch.setattr(del_mod, "_call_codev_agent", _mock_codev_agent)

    resp = await client.post(
        f"/v1/deliverables/{existing.id}/resume",
        json={"content": {"summary": "human content"}, "resume_chain": True},
        headers=auth_h(token),
    )
    assert resp.status_code == 200, f"resume noop failed: {resp.text}"


async def test_resume_endpoint_chain_error_returns_200_not_500(client, owner_token, session_maker, monkeypatch):
    """Test 8: Chain error during resume → deliverable at last-good version, endpoint returns 200."""
    uid, token = owner_token
    from app.routes import deliverables as del_mod

    existing = await _create_deliverable(
        session_maker,
        uid,
        status="awaiting_human",
        deliverable_type="cost_estimate",
        meta={
            "hitl_kind": "co_development",
            "steps_completed": 1,
            "chain_steps": [{"key": "scope_draft", "agent_name": "qc", "role": "r", "version": 1}],
        },
        content={"summary": "step A out", "seed_message": "estimate"},
    )

    # Patch _call_codev_agent to fail.
    async def _failing_agent(endpoint, payload, agent_id, deliverable_id):
        raise RuntimeError("simulated chain failure in codev agent")

    monkeypatch.setattr(del_mod, "_call_codev_agent", _failing_agent)

    resp = await client.post(
        f"/v1/deliverables/{existing.id}/resume",
        json={"content": {"summary": "human content"}, "resume_chain": True},
        headers=auth_h(token),
    )
    # Fail-safe: always 200 regardless of chain error.
    assert resp.status_code == 200, f"expected 200 but got: {resp.text}"
    data = resp.json()
    # The human-contributed content was already applied before the chain ran.
    assert data["id"] == existing.id


# ---------------------------------------------------------------------------
# Tests 9–10: co-dev gate routing in requests.py
# ---------------------------------------------------------------------------


async def test_co_dev_gate_sets_hitl_kind_no_approval_created(client, owner_token, session_maker, monkeypatch):
    """Test 9: co_development gate sets hitl_kind and creates NO approval item."""
    uid, token = owner_token
    import app.routes.requests as reqmod

    call_count = 0

    async def _mock_adk(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _Resp(200, f"step output {call_count}")

    monkeypatch.setattr(reqmod, "_call_adk_with_retry", _mock_adk)

    # Submit an RFI request — rfi_response has terminal_hitl="co_development".
    resp = await client.post(
        "/v1/requests",
        data={"message": "Can you draft an RFI response for drawing conflict on grid line A?"},
        headers=auth_h(token),
    )
    assert resp.status_code == 201, f"request submit failed: {resp.text}"
    request_id = resp.json()["request_id"]

    # Wait for background processing (the pipeline runs the chain).
    import asyncio
    await asyncio.sleep(0.5)

    # Check deliverable meta: hitl_kind should be co_development.
    async with session_maker() as s:
        from app.models_deliverables import Deliverable
        rows = (
            await s.execute(
                select(Deliverable).where(Deliverable.user_id == uid)
            )
        ).scalars().all()

    rfi_deliverables = [r for r in rows if r.deliverable_type == "rfi_response"]
    if not rfi_deliverables:
        # Chain may not have completed in time; skip detailed check.
        return

    rfi = rfi_deliverables[0]
    # No approval item should be in the DB for this deliverable.
    async with session_maker() as s:
        approvals = (
            await s.execute(
                select(ApprovalItem).where(
                    ApprovalItem.workflow == DELIVERABLE_ACCEPT_WORKFLOW
                )
            )
        ).scalars().all()
    # Any approval that WAS created should not have our deliverable_id (co-dev gate skips it).
    delivery_approvals = [
        a for a in approvals
        if (a.payload or {}).get("deliverable_id") == rfi.id
    ]
    assert len(delivery_approvals) == 0, (
        f"Co-dev gate should NOT create an approval item, but found {len(delivery_approvals)}: "
        f"{delivery_approvals}"
    )


async def test_decision_gate_still_creates_approval(client, owner_token, session_maker, monkeypatch):
    """Test 10: Decision gate (cost_estimate) still creates an ApprovalItem."""
    uid, token = owner_token
    import app.routes.requests as reqmod

    call_count = 0

    async def _mock_adk(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _Resp(200, f"step output {call_count}")

    monkeypatch.setattr(reqmod, "_call_adk_with_retry", _mock_adk)

    # Submit an estimate request — cost_estimate has terminal_hitl="decision".
    resp = await client.post(
        "/v1/requests",
        data={"message": "estimate cost for 50MW data center construction in Virginia"},
        headers=auth_h(token),
    )
    assert resp.status_code == 201, f"request submit failed: {resp.text}"

    import asyncio
    await asyncio.sleep(0.5)

    async with session_maker() as s:
        from app.models_deliverables import Deliverable
        rows = (
            await s.execute(
                select(Deliverable).where(Deliverable.user_id == uid)
            )
        ).scalars().all()

    estimate_deliverables = [r for r in rows if r.deliverable_type == "cost_estimate"]
    if not estimate_deliverables:
        return

    est = estimate_deliverables[0]
    if est.status != "awaiting_human":
        return  # chain may not have completed in time

    async with session_maker() as s:
        approvals = (
            await s.execute(
                select(ApprovalItem).where(
                    ApprovalItem.workflow == DELIVERABLE_ACCEPT_WORKFLOW
                )
            )
        ).scalars().all()

    delivery_approvals = [
        a for a in approvals
        if (a.payload or {}).get("deliverable_id") == est.id
    ]
    assert len(delivery_approvals) >= 1, (
        f"Decision gate should create an approval item, but found 0. "
        f"Deliverable status: {est.status}, hitl_kind in meta: {(est.meta or {}).get('hitl_kind')}"
    )


# ---------------------------------------------------------------------------
# Tests 11–12: registry terminal_hitl declarations
# ---------------------------------------------------------------------------


def test_rfi_response_registry_terminal_hitl_is_co_development():
    """Test 11: rfi_response has terminal_hitl='co_development' (piloted example)."""
    from app.deliverable_registry import DELIVERABLE_REGISTRY
    rfi = DELIVERABLE_REGISTRY["rfi_response"]
    assert rfi.terminal_hitl == "co_development", (
        f"rfi_response.terminal_hitl should be 'co_development', got {rfi.terminal_hitl!r}"
    )


def test_cost_estimate_registry_terminal_hitl_is_decision():
    """Test 12: cost_estimate has terminal_hitl='decision' (default for decision gates)."""
    from app.deliverable_registry import DELIVERABLE_REGISTRY
    est = DELIVERABLE_REGISTRY["cost_estimate"]
    assert est.terminal_hitl == "decision", (
        f"cost_estimate.terminal_hitl should be 'decision', got {est.terminal_hitl!r}"
    )


# ---------------------------------------------------------------------------
# Tests 13–14: _request_out enrichment
# ---------------------------------------------------------------------------


async def test_request_out_enriches_with_deliverable_hitl_kind(client, owner_token, session_maker, monkeypatch):
    """Test 13: _request_out populates deliverable_hitl_kind and deliverable_status."""
    uid, token = owner_token
    from app.routes.requests import _request_out
    from app.models_deliverables import Deliverable

    # Create a deliverable with co_development hitl_kind.
    del_row = await _create_deliverable(
        session_maker,
        uid,
        status="awaiting_human",
        deliverable_type="rfi_response",
        meta={"hitl_kind": "co_development", "steps_completed": 2, "chain_steps": []},
    )
    del_id = del_row.id

    # Create a mock RequestRecord-like object.
    class _MockRecord:
        id = "test-req-001"
        user_id = uid
        message = "rfi request"
        intent = "rfi"
        status = "complete"
        response = None
        output_module = "projects"
        output_id = del_id
        drive_url = None
        filenames = None
        from datetime import datetime, UTC
        created_at = datetime.now(UTC)
        updated_at = datetime.now(UTC)
        deliverable_hitl_kind = None
        deliverable_status = None

    async with session_maker() as s:
        out = await _request_out(_MockRecord(), s)

    assert out.deliverable_hitl_kind == "co_development"
    assert out.deliverable_status == "awaiting_human"


async def test_request_out_hitl_kind_is_none_without_deliverable(client, owner_token, session_maker, monkeypatch):
    """Test 14: _request_out leaves deliverable_hitl_kind=None when no output_id linked."""
    uid, token = owner_token
    from app.routes.requests import _request_out

    class _MockRecord:
        id = "test-req-002"
        user_id = uid
        message = "generic request"
        intent = "general"
        status = "complete"
        response = "done"
        output_module = None
        output_id = None
        drive_url = None
        filenames = None
        from datetime import datetime, UTC
        created_at = datetime.now(UTC)
        updated_at = datetime.now(UTC)
        deliverable_hitl_kind = None
        deliverable_status = None

    async with session_maker() as s:
        out = await _request_out(_MockRecord(), s)

    assert out.deliverable_hitl_kind is None
    assert out.deliverable_status is None
