"""Phase D — Deliverable HITL pause/resume tests.

Scenarios verified:
  1. A completed estimate chain (all steps succeed → status='awaiting_human')
     creates BOTH a Deliverable at 'awaiting_human' AND an ApprovalItem with
     workflow='deliverable.accept' that carries the deliverable_id in its payload.
  2. Approving the ApprovalItem executes the hook: the deliverable status
     transitions to 'approved' and a new version is appended recording the
     human_decision in meta.
  3. Rejecting the ApprovalItem sets the deliverable to 'rejected' and records
     the decision in a new version's meta.
  4. A non-owner cannot decide the approval (it requires owner single-sig).
  5. Approval-creation failure does NOT fail the request (fail-safe); the
     deliverable stays at 'awaiting_human'.
  6. Idempotency: if the deliverable is already 'approved', the finalize hook
     is a no-op (returns without re-applying).

Test style follows test_deliverable_pipeline.py:
  - ``client`` fixture for SessionLocal patch
  - ``owner_token`` / ``partner_token`` fixtures for user setup
  - ``monkeypatch`` to control ADK calls
  - Direct DB inspection via db_module.SessionLocal
"""

from __future__ import annotations

import os
import pytest
from sqlalchemy import select

# Import models at top level so create_all registers them (conftest quirk).
import app.routes.requests  # noqa: F401
from app.models import ApprovalItem
from app.models_deliverables import Deliverable, DeliverableVersion
from app.models_requests import RequestRecord
from app.enums import DELIVERABLE_ACCEPT_WORKFLOW

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Resp:
    """Mock HTTP response returned by the patched _call_adk_with_retry."""

    def __init__(self, text: str = "agent output") -> None:
        self.status_code = 200
        self.text = text

    def json(self) -> dict:
        return {"response": self.text}


def auth_h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def agent_h() -> dict:
    return {"X-Agent-Secret": os.environ["AGENT_SHARED_SECRET"]}


async def _seed_and_dispatch(
    client,
    monkeypatch,
    uid: str,
    intent: str,
    message: str,
    adk_responses: list[str] | None = None,
):
    """Seed a processing request and run the producer with controlled ADK responses."""
    import app.db as db_module
    import app.routes.requests as reqmod

    async with db_module.SessionLocal() as s:
        rec = RequestRecord(user_id=uid, message=message, intent=intent, status="processing")
        s.add(rec)
        await s.commit()
        await s.refresh(rec)
        rid = rec.id

    responses = list(adk_responses) if adk_responses else ["agent output A", "agent output B"]
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
    return rid


async def _get_deliverables(uid: str) -> list[Deliverable]:
    import app.db as db_module
    async with db_module.SessionLocal() as s:
        rows = (
            await s.execute(select(Deliverable).where(Deliverable.user_id == uid))
        ).scalars().all()
        return list(rows)


async def _get_approvals_for_workflow(workflow: str) -> list[ApprovalItem]:
    import app.db as db_module
    async with db_module.SessionLocal() as s:
        rows = (
            await s.execute(select(ApprovalItem).where(ApprovalItem.workflow == workflow))
        ).scalars().all()
        return list(rows)


async def _get_versions(deliverable_id: str) -> list[DeliverableVersion]:
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


# ---------------------------------------------------------------------------
# Test 1: Completed estimate chain → deliverable 'awaiting_human' + approval item
# ---------------------------------------------------------------------------


async def test_estimate_chain_creates_approval_at_awaiting_human(
    client, owner_token, monkeypatch
):
    """After a full estimate chain, the deliverable is 'awaiting_human' AND an
    ApprovalItem with workflow='deliverable.accept' exists, linked to it."""
    uid, _ = owner_token

    await _seed_and_dispatch(
        client, monkeypatch, uid, "estimate", "Price 500 LF conduit",
        adk_responses=["Scope draft output", "ROM pricing output"],
    )

    # Deliverable should be at awaiting_human
    dels = await _get_deliverables(uid)
    assert len(dels) == 1, f"Expected 1 deliverable, got {len(dels)}"
    d = dels[0]
    assert d.status == "awaiting_human", f"Expected 'awaiting_human', got {d.status!r}"
    assert d.version >= 2

    # An ApprovalItem with workflow='deliverable.accept' should exist
    approvals = await _get_approvals_for_workflow(DELIVERABLE_ACCEPT_WORKFLOW)
    assert len(approvals) >= 1, f"Expected >=1 approval with workflow={DELIVERABLE_ACCEPT_WORKFLOW!r}"

    # The approval payload must carry the deliverable_id
    approval = approvals[0]
    payload = approval.payload or {}
    assert payload.get("deliverable_id") == d.id, (
        f"Approval payload.deliverable_id={payload.get('deliverable_id')!r} != {d.id!r}"
    )
    assert payload.get("deliverable_type") == "cost_estimate"

    # Lane must be SINGLE (2) — never auto
    from app.enums import Lane
    assert approval.lane == Lane.SINGLE.value, (
        f"Expected Lane.SINGLE (2), got {approval.lane}"
    )

    # Status must be 'pending' (human hasn't decided yet)
    assert approval.status == "pending", f"Expected 'pending', got {approval.status!r}"


async def test_rfi_chain_creates_approval_at_awaiting_human(
    client, owner_token, monkeypatch
):
    """RFI chain also produces an approval item at awaiting_human."""
    uid, _ = owner_token

    await _seed_and_dispatch(
        client, monkeypatch, uid, "rfi", "Clarify slab spec",
        adk_responses=["RFI intake output", "RFI draft output"],
    )

    dels = await _get_deliverables(uid)
    assert len(dels) == 1
    d = dels[0]
    assert d.status == "awaiting_human"
    assert d.deliverable_type == "rfi_response"

    approvals = await _get_approvals_for_workflow(DELIVERABLE_ACCEPT_WORKFLOW)
    assert len(approvals) >= 1
    approval = approvals[0]
    assert (approval.payload or {}).get("deliverable_id") == d.id


# ---------------------------------------------------------------------------
# Test 2: Approving the approval finalizes deliverable → 'approved'
# ---------------------------------------------------------------------------


async def test_approve_finalizes_deliverable_to_approved(
    client, owner_token, monkeypatch
):
    """Approving the ApprovalItem transitions deliverable to 'approved' and
    appends a new version recording the human_decision in meta."""
    uid, tok = owner_token

    await _seed_and_dispatch(
        client, monkeypatch, uid, "estimate", "Trench 200 LF",
        adk_responses=["Scope draft", "ROM estimate"],
    )

    dels = await _get_deliverables(uid)
    assert len(dels) == 1
    d = dels[0]
    assert d.status == "awaiting_human"
    initial_version = d.version

    approvals = await _get_approvals_for_workflow(DELIVERABLE_ACCEPT_WORKFLOW)
    assert len(approvals) >= 1
    approval_id = approvals[0].id

    # Owner approves
    r = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "approve"},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, f"Approve failed: {r.text}"

    # Deliverable must now be 'approved'
    dels2 = await _get_deliverables(uid)
    assert len(dels2) == 1
    d2 = dels2[0]
    assert d2.status == "approved", f"Expected 'approved', got {d2.status!r}"

    # A new version was appended recording the decision
    assert d2.version > initial_version, (
        f"Expected version > {initial_version}, got {d2.version}"
    )

    # The new version's meta must contain human_decision
    meta = d2.meta or {}
    hd = meta.get("human_decision", {})
    assert hd.get("decision") == "approved", f"meta.human_decision={hd}"
    assert hd.get("approval_id") == approval_id


async def test_approve_appends_version_with_decision(
    client, owner_token, monkeypatch
):
    """After approval, version history has a new snapshot with status='approved'."""
    uid, tok = owner_token

    await _seed_and_dispatch(
        client, monkeypatch, uid, "estimate", "Foundation cost",
        adk_responses=["Scope", "Pricing"],
    )

    dels = await _get_deliverables(uid)
    d = dels[0]
    approvals = await _get_approvals_for_workflow(DELIVERABLE_ACCEPT_WORKFLOW)
    approval_id = approvals[0].id

    versions_before = await _get_versions(d.id)

    r = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "approve"},
        headers=auth_h(tok),
    )
    assert r.status_code == 200

    versions_after = await _get_versions(d.id)
    assert len(versions_after) > len(versions_before), (
        "Expected a new version snapshot after approval"
    )

    # Last snapshot must be 'approved'
    last = versions_after[-1]
    assert last.status == "approved", f"Last snapshot status={last.status!r}"
    assert last.change_action == "updated"


# ---------------------------------------------------------------------------
# Test 3: Rejecting the approval sets deliverable to 'rejected'
# ---------------------------------------------------------------------------


async def test_reject_finalizes_deliverable_to_rejected(
    client, owner_token, monkeypatch
):
    """Rejecting the ApprovalItem transitions deliverable to 'rejected' and
    records the rejection_reason in the new version's meta."""
    uid, tok = owner_token

    await _seed_and_dispatch(
        client, monkeypatch, uid, "estimate", "Electrical scope check",
        adk_responses=["Scope draft", "ROM estimate"],
    )

    dels = await _get_deliverables(uid)
    d = dels[0]
    assert d.status == "awaiting_human"

    approvals = await _get_approvals_for_workflow(DELIVERABLE_ACCEPT_WORKFLOW)
    approval_id = approvals[0].id

    r = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "reject", "rejection_reason": "Scope is incomplete"},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, f"Reject failed: {r.text}"

    dels2 = await _get_deliverables(uid)
    d2 = dels2[0]
    assert d2.status == "rejected", f"Expected 'rejected', got {d2.status!r}"

    # A new version was appended
    versions = await _get_versions(d2.id)
    last = versions[-1]
    assert last.status == "rejected"

    # human_decision in meta
    meta = d2.meta or {}
    hd = meta.get("human_decision", {})
    assert hd.get("decision") == "rejected", f"meta.human_decision={hd}"
    assert hd.get("rejection_reason") == "Scope is incomplete"


# ---------------------------------------------------------------------------
# Test 4: Non-owner cannot decide the approval (owner-only via required_approvers)
# ---------------------------------------------------------------------------


async def test_partner_cannot_decide_deliverable_approval(
    client, owner_token, partner_token, monkeypatch
):
    """The approval lane is SINGLE with required_approvers=[owner].  A partner
    (role='partner') must not be able to approve a deliverable gate."""
    uid_owner, _ = owner_token
    _, tok_partner = partner_token

    await _seed_and_dispatch(
        client, monkeypatch, uid_owner, "estimate", "HVAC estimate",
        adk_responses=["Scope A", "Pricing B"],
    )

    approvals = await _get_approvals_for_workflow(DELIVERABLE_ACCEPT_WORKFLOW)
    assert len(approvals) >= 1
    approval_id = approvals[0].id

    # Partner tries to approve — must be rejected (403)
    r = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "approve"},
        headers=auth_h(tok_partner),
    )
    assert r.status_code in (403, 422), (
        f"Expected 403/422 for non-owner deciding owner-only approval, got {r.status_code}: {r.text}"
    )

    # Deliverable must still be awaiting_human
    dels = await _get_deliverables(uid_owner)
    assert dels[0].status == "awaiting_human", (
        f"Deliverable should still be awaiting_human after failed partner decision"
    )


# ---------------------------------------------------------------------------
# Test 5: Approval-creation failure does NOT fail the request
# ---------------------------------------------------------------------------


async def test_approval_creation_failure_does_not_fail_request(
    client, owner_token, monkeypatch
):
    """If create_deliverable_approval raises, the request must still succeed
    (status='complete') and the deliverable stays at 'awaiting_human'."""
    import app.db as db_module
    import app.routes.requests as reqmod
    import app.services.deliverable_hitl as hitl_mod

    uid, _ = owner_token

    # Force approval creation to fail
    async def _boom(*a, **k):
        raise RuntimeError("simulated approval-service outage")

    monkeypatch.setattr(hitl_mod, "create_deliverable_approval", _boom)

    rid = await _seed_and_dispatch(
        client, monkeypatch, uid, "estimate", "Budget cost only",
        adk_responses=["Scope", "Pricing"],
    )

    # Request must be complete (chain succeeded)
    async with db_module.SessionLocal() as s:
        rec = await s.get(RequestRecord, rid)
    assert rec is not None
    assert rec.status == "complete", f"Expected 'complete', got {rec.status!r}"

    # Deliverable exists and stays awaiting_human
    dels = await _get_deliverables(uid)
    assert len(dels) == 1
    assert dels[0].status == "awaiting_human", (
        f"Deliverable should be 'awaiting_human' when approval creation failed, "
        f"got {dels[0].status!r}"
    )


# ---------------------------------------------------------------------------
# Test 6: Idempotency — finalizing an already-approved deliverable is a no-op
# ---------------------------------------------------------------------------


async def test_finalize_already_approved_is_noop(client, owner_token):
    """If the deliverable is already 'approved', finalize_deliverable_on_approval
    returns without re-applying (no extra version bump)."""
    import app.db as db_module
    from app.routes.deliverables import (
        create_deliverable_service,
        append_deliverable_version_service,
    )
    from app.services.deliverable_hitl import finalize_deliverable_on_approval
    from app.models import ApprovalItem as _ApprovalItem
    from app.enums import DELIVERABLE_ACCEPT_WORKFLOW as _WF

    uid, _ = owner_token

    # Create a deliverable and manually set it to 'approved'
    async with db_module.SessionLocal() as s:
        row = await create_deliverable_service(
            s, user_id=uid, project_id=None,
            module_key="estimates", deliverable_type="cost_estimate",
            title="Test idempotency", content={"summary": "done"},
        )
        row = await append_deliverable_version_service(
            s, row, status="approved", change_action="updated"
        )
        deliverable_id = row.id
        version_before = row.version

    # Build a fake approval item pointing to this deliverable
    async with db_module.SessionLocal() as s:
        fake_item = _ApprovalItem(
            agent_id="deliverable-hitl",
            agent_version="phase-d",
            workflow=_WF,
            lane=2,
            priority="normal",
            target_system="none",
            payload={"deliverable_id": deliverable_id},
            required_approvers=["owner"],
            status="executed",
        )
        s.add(fake_item)
        await s.commit()
        await s.refresh(fake_item)

        # Call finalize — should be a no-op since status != awaiting_human
        result = await finalize_deliverable_on_approval(
            s, fake_item, actor=uid, approved=True
        )

    # Version must not have increased
    async with db_module.SessionLocal() as s:
        row2 = await s.get(
            __import__("app.models_deliverables", fromlist=["Deliverable"]).Deliverable,
            deliverable_id,
        )

    assert row2 is not None
    assert row2.status == "approved"
    assert row2.version == version_before, (
        f"Idempotent finalize should not bump version: before={version_before}, after={row2.version}"
    )


# ---------------------------------------------------------------------------
# Test 7: Direct unit test of create_deliverable_approval
# ---------------------------------------------------------------------------


async def test_create_deliverable_approval_direct(client, owner_token):
    """Directly call create_deliverable_approval; verify lane, workflow, payload."""
    import app.db as db_module
    from app.routes.deliverables import create_deliverable_service, append_deliverable_version_service
    from app.services.deliverable_hitl import create_deliverable_approval
    from app.enums import Lane, DELIVERABLE_ACCEPT_WORKFLOW as _WF

    uid, _ = owner_token

    async with db_module.SessionLocal() as s:
        row = await create_deliverable_service(
            s, user_id=uid, project_id=None,
            module_key="estimates", deliverable_type="cost_estimate",
            title="Direct test estimate", content={"summary": "step A output"},
        )
        row = await append_deliverable_version_service(
            s, row, status="awaiting_human", change_action="updated"
        )
        approval = await create_deliverable_approval(
            s, row, actor=uid,
            summary="Review and approve this cost estimate."
        )

    assert approval.workflow == _WF
    assert approval.lane == Lane.SINGLE.value
    assert approval.status == "pending"
    payload = approval.payload or {}
    assert payload.get("deliverable_id") == row.id
    assert payload.get("deliverable_type") == "cost_estimate"
    assert "Review" in payload.get("summary", "")


# ---------------------------------------------------------------------------
# Test 8: finalize_deliverable_on_approval with missing deliverable_id
# ---------------------------------------------------------------------------


async def test_finalize_missing_deliverable_id_returns_none(client, owner_token):
    """If approval payload has no deliverable_id, finalize returns None (gracefully)."""
    import app.db as db_module
    from app.services.deliverable_hitl import finalize_deliverable_on_approval
    from app.models import ApprovalItem as _ApprovalItem

    uid, _ = owner_token

    async with db_module.SessionLocal() as s:
        fake_item = _ApprovalItem(
            agent_id="deliverable-hitl",
            agent_version="phase-d",
            workflow=DELIVERABLE_ACCEPT_WORKFLOW,
            lane=2,
            priority="normal",
            target_system="none",
            payload={},  # no deliverable_id
            required_approvers=["owner"],
            status="executed",
        )
        s.add(fake_item)
        await s.commit()
        await s.refresh(fake_item)

        result = await finalize_deliverable_on_approval(
            s, fake_item, actor=uid, approved=True
        )

    assert result is None


# ---------------------------------------------------------------------------
# Test 9: Approve via API returns 'executed' status
# ---------------------------------------------------------------------------


async def test_approval_status_executed_after_approve(
    client, owner_token, monkeypatch
):
    """After owner approves, the ApprovalItem status should be 'executed'."""
    uid, tok = owner_token

    await _seed_and_dispatch(
        client, monkeypatch, uid, "estimate", "Site grading estimate",
        adk_responses=["Scope draft", "ROM estimate"],
    )

    approvals = await _get_approvals_for_workflow(DELIVERABLE_ACCEPT_WORKFLOW)
    assert len(approvals) >= 1
    approval_id = approvals[0].id

    r = await client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "approve"},
        headers=auth_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    # After approve + execute, status should be 'executed'
    assert body["status"] == "executed", f"Expected 'executed', got {body['status']!r}"
