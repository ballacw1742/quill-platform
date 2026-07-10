"""Phase C — deliverable pipeline orchestrator tests.

Tests for the multi-step deliverable chain introduced in Phase C.

Scenarios verified:
  1. An estimate chain produces a deliverable with >=2 versions (v1 from step A,
     v2 from step B building on it), meta records both step keys, and the final
     status is 'awaiting_human'.
  2. An RFI chain likewise produces >=2 versions with step lineage and final
     status 'awaiting_human'.
  3. A mid-chain step failure (step B fails) leaves the deliverable at its last
     good version (v1) with status unchanged (not crashed), and does NOT fail
     the enclosing request.
  4. A non-piloted intent (no chain) still produces nothing — Phase B fallback
     is bypassed and the registry has no steps to run.
  5. Full integration via _dispatch_to_agent: piloted intent with two distinct
     ADK responses produces a deliverable with >=2 versions and status
     'awaiting_human', with each call building on prior output.
  6. Step A failure (first agent call fails) leaves no deliverable created.

These use the ``client`` fixture because it monkeypatches app.db.SessionLocal to
the in-memory test session maker — which is the session maker the background
pipeline opens internally. Without the client fixture, SessionLocal points at
the real DB and the tables don't exist.

Test style mirrors test_deliverable_producer.py:
  - ``client`` fixture for SessionLocal patch
  - ``owner_token`` fixture for user setup
  - ``monkeypatch`` to control ADK calls
  - Direct DB inspection via db_module.SessionLocal
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

# Import models at top level so create_all registers them (conftest quirk).
import app.routes.requests  # noqa: F401
from app.deliverable_registry import INTENT_TO_DELIVERABLE, DELIVERABLE_REGISTRY
from app.models_deliverables import Deliverable, DeliverableVersion
from app.models_requests import RequestRecord

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _Resp:
    """Mock HTTP response returned by the patched _call_adk_with_retry."""

    def __init__(self, text: str = "agent output") -> None:
        self.status_code = 200
        self.text = text

    def json(self) -> dict:
        return {"response": self.text}


async def _deliverables_for(uid: str) -> list[Deliverable]:
    import app.db as db_module
    async with db_module.SessionLocal() as s:
        rows = (
            await s.execute(select(Deliverable).where(Deliverable.user_id == uid))
        ).scalars().all()
        return list(rows)


async def _versions_for(deliverable_id: str) -> list[DeliverableVersion]:
    import app.db as db_module
    async with db_module.SessionLocal() as s:
        rows = (
            await s.execute(
                select(DeliverableVersion)
                .where(DeliverableVersion.deliverable_id == deliverable_id)
                .order_by(DeliverableVersion.version.asc())
            )
        ).scalars().all()
        return list(rows)


async def _seed_and_dispatch(
    client,
    monkeypatch,
    uid: str,
    intent: str,
    message: str,
    adk_responses: list[str] | None = None,
):
    """Seed a processing request and run the producer with controlled ADK responses.

    ``adk_responses`` is a list of text strings; each successive call to
    _call_adk_with_retry pops the next entry. If None, defaults to a single
    generic response (backward-compat).
    """
    import app.db as db_module
    import app.routes.requests as reqmod

    async with db_module.SessionLocal() as s:
        rec = RequestRecord(user_id=uid, message=message, intent=intent, status="processing")
        s.add(rec)
        await s.commit()
        await s.refresh(rec)
        rid = rec.id

    # Build response queue
    responses = list(adk_responses) if adk_responses else ["agent output"]
    call_count = [0]

    async def _fake_adk(*a, **k):
        idx = call_count[0]
        call_count[0] += 1
        text = responses[idx] if idx < len(responses) else responses[-1]
        return _Resp(text)

    monkeypatch.setattr(reqmod, "_call_adk_with_retry", _fake_adk)
    await reqmod._dispatch_to_agent(
        request_id=rid,
        intent=intent,
        message=message,
        filenames=[],
        drive_url=None,
        user_id=uid,
    )
    return rid, call_count[0]


# ---------------------------------------------------------------------------
# Test: estimate chain produces >=2 versions with correct lineage and status
# ---------------------------------------------------------------------------


async def test_estimate_chain_produces_two_versions(client, owner_token, monkeypatch):
    """Step A produces v1, step B appends v2 building on step A's output.
    Final status is 'awaiting_human'. Meta records both step keys.
    """
    uid, _ = owner_token

    # Provide two distinct responses so we can verify ordering / lineage.
    rid, call_count = await _seed_and_dispatch(
        client, monkeypatch, uid, "estimate", "Price 200 LF trench",
        adk_responses=["Scope draft output A", "Unit pricing output B"],
    )

    dels = await _deliverables_for(uid)
    assert len(dels) == 1, f"Expected 1 deliverable, got {len(dels)}"
    d = dels[0]

    # Type and module
    assert d.deliverable_type == "cost_estimate"
    assert d.module_key == "estimates"

    # Two versions produced (v1 from step A, v2 from step B)
    assert d.version >= 2, f"Expected version >=2, got {d.version}"

    # Final status after completing all steps
    assert d.status == "awaiting_human", f"Expected 'awaiting_human', got {d.status!r}"

    # Both step keys recorded in meta
    meta = d.meta or {}
    completed_steps = meta.get("chain_steps", [])
    step_keys = [s["key"] for s in completed_steps]
    assert "scope_draft" in step_keys, f"step_keys={step_keys}"
    assert "unit_pricing" in step_keys, f"step_keys={step_keys}"
    assert meta.get("steps_completed") == 2

    # ADK was called twice (once per step)
    assert call_count >= 2, f"Expected >=2 ADK calls, got {call_count}"


async def test_estimate_chain_version_snapshots(client, owner_token, monkeypatch):
    """Version history has entries for v1 (created) and v2 (updated)."""
    uid, _ = owner_token

    await _seed_and_dispatch(
        client, monkeypatch, uid, "estimate", "Budget check",
        adk_responses=["Step A output", "Step B output"],
    )

    dels = await _deliverables_for(uid)
    assert len(dels) == 1
    versions = await _versions_for(dels[0].id)

    # Must have >=2 version snapshots
    assert len(versions) >= 2, f"Expected >=2 version snapshots, got {len(versions)}"

    v1 = versions[0]
    v2 = versions[1]

    # v1 is the 'created' snapshot from step A
    assert v1.version == 1
    assert v1.change_action == "created"

    # v2 is the 'updated' snapshot from step B
    assert v2.version == 2
    assert v2.change_action == "updated"


async def test_estimate_chain_step_b_builds_on_step_a(client, owner_token, monkeypatch):
    """Step B's content must reference step A's output (prior_output in message).

    The _call_adk_with_retry function is called three times in this flow:
      call 0: initial dispatch (request-level ADK call)
      call 1: chain step A (scope_draft)
      call 2: chain step B (unit_pricing) — message should contain step A's output

    We provide 3 distinct responses to match. Step B's message must include
    'Prior step output' and chain step A's actual output text.
    """
    import app.routes.requests as reqmod

    uid, _ = owner_token

    captured_messages: list[tuple[str, str]] = []  # (endpoint, payload_message)

    # 3 responses: [initial dispatch, chain step A, chain step B]
    responses = [
        "Step A: takeoff with quantities",
        "Step B: ROM estimate using Step A output",
    ]
    call_count = [0]

    async def _capture_adk(endpoint, payload, agent_id, request_id):
        captured_messages.append((endpoint, payload.get("message", "")))
        idx = call_count[0]
        call_count[0] += 1
        text = responses[idx] if idx < len(responses) else responses[-1]
        return _Resp(text)

    monkeypatch.setattr(reqmod, "_call_adk_with_retry", _capture_adk)

    import app.db as db_module
    async with db_module.SessionLocal() as s:
        rec = RequestRecord(
            user_id=uid, message="Price the fiber run", intent="estimate", status="processing"
        )
        s.add(rec)
        await s.commit()
        await s.refresh(rec)
        rid = rec.id

    await reqmod._dispatch_to_agent(
        request_id=rid, intent="estimate", message="Price the fiber run",
        filenames=[], drive_url=None, user_id=uid,
    )

    # Phase-C cost model: NO initial dispatch for piloted intents — exactly the
    # 2 chain calls (step A, step B).
    assert call_count[0] == 2, (
        f"Expected exactly 2 ADK calls (2 chain steps, no legacy dispatch), got {call_count[0]}"
    )

    # call 1 is chain step B — its message should include step A's output.
    step_b_msg = captured_messages[1][1] if len(captured_messages) >= 2 else ""

    assert "Prior step output" in step_b_msg, (
        f"Step B message should contain 'Prior step output'. "
        f"Captured step B message: {step_b_msg[:200]}"
    )
    # Step B's message must include step A's response text (the second response)
    assert "Step A: takeoff" in step_b_msg, (
        f"Step B message should include step A's output text. "
        f"Captured step B message: {step_b_msg[:200]}"
    )


# ---------------------------------------------------------------------------
# Test: RFI chain produces >=2 versions with correct lineage and status
# ---------------------------------------------------------------------------


async def test_rfi_chain_produces_two_versions(client, owner_token, monkeypatch):
    """RFI chain: step A = intake/triage, step B = drafted response.
    Final status is 'awaiting_human'. Meta records both step keys.
    """
    uid, _ = owner_token

    rid, call_count = await _seed_and_dispatch(
        client, monkeypatch, uid, "rfi", "Clarify slab spec",
        adk_responses=["RFI intake triage output", "RFI drafted response output"],
    )

    dels = await _deliverables_for(uid)
    assert len(dels) == 1
    d = dels[0]

    assert d.deliverable_type == "rfi_response"
    assert d.module_key == "projects"
    assert d.version >= 2, f"Expected version >=2, got {d.version}"
    assert d.status == "awaiting_human"

    meta = d.meta or {}
    step_keys = [s["key"] for s in meta.get("chain_steps", [])]
    assert "rfi_intake" in step_keys, f"step_keys={step_keys}"
    assert "rfi_draft" in step_keys, f"step_keys={step_keys}"
    assert meta.get("steps_completed") == 2

    assert call_count >= 2


async def test_rfi_chain_version_history(client, owner_token, monkeypatch):
    """RFI version snapshots: v1 'created', v2 'updated'."""
    uid, _ = owner_token

    await _seed_and_dispatch(
        client, monkeypatch, uid, "rfi", "What slab thickness?",
        adk_responses=["Intake output", "Draft response output"],
    )

    dels = await _deliverables_for(uid)
    assert len(dels) == 1
    versions = await _versions_for(dels[0].id)
    assert len(versions) >= 2

    assert versions[0].version == 1 and versions[0].change_action == "created"
    assert versions[1].version == 2 and versions[1].change_action == "updated"


# ---------------------------------------------------------------------------
# Test: mid-chain step failure leaves deliverable at last good version
# ---------------------------------------------------------------------------


async def test_mid_chain_failure_leaves_last_good_version(client, owner_token, monkeypatch):
    """If step B fails, the deliverable stays at v1 (last good). Request does not fail."""
    import app.db as db_module
    import app.routes.requests as reqmod

    uid, _ = owner_token

    call_count = [0]

    async def _fake_adk(*a, **k):
        # Phase-C cost model: 2 chain calls, no legacy dispatch.
        call_count[0] += 1
        if call_count[0] == 1:
            # Chain step A succeeds
            return _Resp("Chain step A output")
        # Chain step B fails
        raise RuntimeError("simulated step B network failure")

    monkeypatch.setattr(reqmod, "_call_adk_with_retry", _fake_adk)

    async with db_module.SessionLocal() as s:
        rec = RequestRecord(
            user_id=uid, message="Price 100 LF conduit", intent="estimate", status="processing"
        )
        s.add(rec)
        await s.commit()
        await s.refresh(rec)
        rid = rec.id

    # Dispatch must complete without raising even if step B fails
    await reqmod._dispatch_to_agent(
        request_id=rid, intent="estimate", message="Price 100 LF conduit",
        filenames=[], drive_url=None, user_id=uid,
    )

    # Step A produced a v1 deliverable, so the request is complete (partial
    # deliverable exists); step B failure just stopped the chain.
    async with db_module.SessionLocal() as s:
        rec = await s.get(RequestRecord, rid)
    assert rec.status == "complete", f"Expected request 'complete', got {rec.status!r}"

    # Deliverable exists (step A created it) but is at v1 (step B failed before appending v2)
    dels = await _deliverables_for(uid)
    assert len(dels) == 1, f"Expected 1 deliverable (from step A), got {len(dels)}"
    d = dels[0]

    # v1 from step A only — step B failure stopped the chain
    assert d.version == 1, f"Expected version 1 (step B failed), got {d.version}"
    # Status should NOT be awaiting_human (that's the terminal state after all steps complete)
    assert d.status != "awaiting_human", (
        f"Status should not be 'awaiting_human' after mid-chain failure, got {d.status!r}"
    )


async def test_mid_chain_failure_deliverable_at_v1_has_step_a_meta(client, owner_token, monkeypatch):
    """On step B failure, the v1 deliverable's meta should still record step A."""
    import app.db as db_module
    import app.routes.requests as reqmod

    uid, _ = owner_token

    call_count = [0]

    async def _fake_adk(*a, **k):
        # 2-call model: step A (call 1) succeeds, step B (call 2) fails.
        call_count[0] += 1
        if call_count[0] <= 1:
            return _Resp("step A output")
        raise RuntimeError("step B failure")

    monkeypatch.setattr(reqmod, "_call_adk_with_retry", _fake_adk)

    async with db_module.SessionLocal() as s:
        rec = RequestRecord(
            user_id=uid, message="Estimate HVAC scope", intent="estimate", status="processing"
        )
        s.add(rec)
        await s.commit()
        await s.refresh(rec)
        rid = rec.id

    await reqmod._dispatch_to_agent(
        request_id=rid, intent="estimate", message="Estimate HVAC scope",
        filenames=[], drive_url=None, user_id=uid,
    )

    dels = await _deliverables_for(uid)
    assert len(dels) == 1
    d = dels[0]

    meta = d.meta or {}
    step_keys = [s["key"] for s in meta.get("chain_steps", [])]
    # Step A should be recorded
    assert "scope_draft" in step_keys, f"step_keys={step_keys}"
    # Step B should NOT be recorded (it failed)
    assert "unit_pricing" not in step_keys, f"step_keys={step_keys}"


# ---------------------------------------------------------------------------
# Test: non-piloted intent produces nothing (chain not triggered)
# ---------------------------------------------------------------------------


async def test_non_piloted_intent_produces_nothing(client, owner_token, monkeypatch):
    """'contract' is not a piloted intent — no deliverable, no chain."""
    uid, _ = owner_token
    assert "contract" not in INTENT_TO_DELIVERABLE

    await _seed_and_dispatch(
        client, monkeypatch, uid, "contract", "Review CO #12",
        adk_responses=["contract review output"],
    )

    dels = await _deliverables_for(uid)
    assert dels == [], f"Expected no deliverables for non-piloted intent, got {dels}"


# ---------------------------------------------------------------------------
# Test: step A failure produces no deliverable and does not fail the request
# ---------------------------------------------------------------------------


async def test_step_a_failure_no_deliverable_request_marked_failed(client, owner_token, monkeypatch):
    """Phase-C cost model: the legacy single dispatch is SKIPPED for piloted
    intents, so the chain is the request's only work. If step A (the FIRST
    agent call) fails, no deliverable is created AND the request is marked
    failed (there is no legacy fallback response). The handler must not crash."""
    import app.db as db_module
    import app.routes.requests as reqmod

    uid, _ = owner_token

    async def _fake_adk(*a, **k):
        # First (and every) chain call fails — step A cannot produce output.
        raise RuntimeError("simulated chain step A failure")

    monkeypatch.setattr(reqmod, "_call_adk_with_retry", _fake_adk)

    async with db_module.SessionLocal() as s:
        rec = RequestRecord(
            user_id=uid, message="Estimate foundation cost", intent="estimate", status="processing"
        )
        s.add(rec)
        await s.commit()
        await s.refresh(rec)
        rid = rec.id

    # Must not raise despite step A failing.
    await reqmod._dispatch_to_agent(
        request_id=rid, intent="estimate", message="Estimate foundation cost",
        filenames=[], drive_url=None, user_id=uid,
    )

    async with db_module.SessionLocal() as s:
        rec = await s.get(RequestRecord, rid)
    # No legacy fallback → the request honestly reflects failure.
    assert rec.status == "failed", f"Expected 'failed', got {rec.status!r}"
    dels = await _deliverables_for(uid)
    assert dels == [], f"Expected no deliverables on step A failure, got {dels}"


# ---------------------------------------------------------------------------
# Test: direct pipeline unit tests (without full dispatch)
# ---------------------------------------------------------------------------


async def test_pipeline_estimate_chain_direct(client, owner_token):
    """Directly call run_deliverable_chain with a mock call_agent.
    Verifies the chain produces >=2 versions and awaiting_human status.
    """
    import app.db as db_module
    from app.deliverable_pipeline import run_deliverable_chain

    uid, _ = owner_token

    call_log: list[tuple[str, str]] = []

    async def _mock_agent(agent_name: str, message: str) -> str:
        call_log.append((agent_name, message))
        if len(call_log) == 1:
            return "Scope draft: items A, B, C"
        return "ROM estimate: $150k total based on scope"

    async with db_module.SessionLocal() as db:
        deliverable = await run_deliverable_chain(
            db,
            user_id=uid,
            project_id=None,
            deliverable_type="cost_estimate",
            seed_message="Estimate electrical scope",
            call_agent=_mock_agent,
        )

    assert deliverable is not None
    assert deliverable.version >= 2
    assert deliverable.status == "awaiting_human"
    assert deliverable.deliverable_type == "cost_estimate"

    meta = deliverable.meta or {}
    step_keys = [s["key"] for s in meta.get("chain_steps", [])]
    assert "scope_draft" in step_keys
    assert "unit_pricing" in step_keys

    # Verify step B received step A's output as context
    assert len(call_log) == 2
    _, step_b_msg = call_log[1]
    assert "Scope draft: items A, B, C" in step_b_msg, (
        f"Step B should include step A's output. Got: {step_b_msg[:200]}"
    )


async def test_pipeline_rfi_chain_direct(client, owner_token):
    """Directly test the RFI chain via run_deliverable_chain."""
    import app.db as db_module
    from app.deliverable_pipeline import run_deliverable_chain

    uid, _ = owner_token

    call_log: list[tuple[str, str]] = []

    async def _mock_agent(agent_name: str, message: str) -> str:
        call_log.append((agent_name, message))
        if len(call_log) == 1:
            return "RFI triage: clarification needed on slab thickness"
        return "Drafted RFI response: slab thickness per spec section 3.2"

    async with db_module.SessionLocal() as db:
        deliverable = await run_deliverable_chain(
            db,
            user_id=uid,
            project_id=None,
            deliverable_type="rfi_response",
            seed_message="What is the required slab thickness?",
            call_agent=_mock_agent,
        )

    assert deliverable is not None
    assert deliverable.version >= 2
    assert deliverable.status == "awaiting_human"
    assert deliverable.deliverable_type == "rfi_response"
    assert deliverable.module_key == "projects"

    meta = deliverable.meta or {}
    step_keys = [s["key"] for s in meta.get("chain_steps", [])]
    assert "rfi_intake" in step_keys
    assert "rfi_draft" in step_keys

    # Step B should include step A's output
    assert len(call_log) == 2
    _, step_b_msg = call_log[1]
    assert "triage: clarification" in step_b_msg


async def test_pipeline_no_steps_returns_none(client, owner_token):
    """run_deliverable_chain returns None for a type with no steps (non-piloted fallback)."""
    import app.db as db_module
    from app.deliverable_pipeline import run_deliverable_chain

    uid, _ = owner_token

    # Temporarily test with a known non-existent type (registry lookup returns None)
    async def _mock_agent(agent_name: str, message: str) -> str:
        return "output"

    async with db_module.SessionLocal() as db:
        result = await run_deliverable_chain(
            db,
            user_id=uid,
            project_id=None,
            deliverable_type="nonexistent_type",
            seed_message="test",
            call_agent=_mock_agent,
        )

    assert result is None


async def test_pipeline_chain_step_b_failure_returns_v1(client, owner_token):
    """If step B fails, run_deliverable_chain returns the v1 row (last good)."""
    import app.db as db_module
    from app.deliverable_pipeline import run_deliverable_chain

    uid, _ = owner_token

    call_count = [0]

    async def _failing_step_b(agent_name: str, message: str) -> str:
        call_count[0] += 1
        if call_count[0] == 1:
            return "Step A output"
        raise RuntimeError("step B agent failure")

    async with db_module.SessionLocal() as db:
        deliverable = await run_deliverable_chain(
            db,
            user_id=uid,
            project_id=None,
            deliverable_type="cost_estimate",
            seed_message="test estimate",
            call_agent=_failing_step_b,
        )

    # Deliverable created from step A but chain stopped
    assert deliverable is not None
    assert deliverable.version == 1, f"Expected v1 (step B failed), got v{deliverable.version}"
    # Status is whatever create_deliverable_service sets (draft) — NOT awaiting_human
    assert deliverable.status != "awaiting_human"


# ---------------------------------------------------------------------------
# Test: registry structure sanity (both pilots have >=2 steps)
# These are sync tests — no asyncio mark needed.
# ---------------------------------------------------------------------------


def test_registry_cost_estimate_has_two_steps():
    """cost_estimate registry entry has >=2 steps with expected keys."""
    entry = DELIVERABLE_REGISTRY["cost_estimate"]
    assert len(entry.steps) >= 2
    keys = [s.key for s in entry.steps]
    assert "scope_draft" in keys
    assert "unit_pricing" in keys


def test_registry_rfi_response_has_two_steps():
    """rfi_response registry entry has >=2 steps with expected keys."""
    entry = DELIVERABLE_REGISTRY["rfi_response"]
    assert len(entry.steps) >= 2
    keys = [s.key for s in entry.steps]
    assert "rfi_intake" in keys
    assert "rfi_draft" in keys


def test_registry_steps_have_required_fields():
    """All chain steps have non-empty key and agent_name."""
    for type_key, entry in DELIVERABLE_REGISTRY.items():
        for step in entry.steps:
            assert step.key, f"{type_key}: step.key is empty"
            assert step.agent_name, f"{type_key}: step.agent_name is empty"
            assert step.prompt_suffix, f"{type_key}: step.prompt_suffix is empty"
