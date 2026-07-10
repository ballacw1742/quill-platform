"""Phase G1 — Co-development endpoint + resume + HITL kind tests.

Scenarios verified (~15 tests):

  1.  codev returns proposed content WITHOUT committing (version unchanged,
      status unchanged, no new DeliverableVersion row).
  2.  codev accept via resume commits exactly ONE new version with
      change_action="co_developed" and moves off awaiting_human.
  3.  resume with resume_chain=True sets status to 'in_progress' (documents
      the mid-chain auto-resume limitation).
  4.  resume with resume_chain=False sets status to 'approved'.
  5.  ADK/agent failure in codev → 502 AND live deliverable byte-for-byte
      untouched (version and content unchanged).
  6.  ADK non-200 status in codev → 502 AND live deliverable untouched.
  7.  hitl_kind: co_development gate does NOT create an ApprovalItem.
  8.  hitl_kind: decision gate still creates an ApprovalItem (existing
      behavior preserved).
  9.  drive_url surfaced when a drive block exists in content.
  10. drive_url surfaced when a drive block exists in meta.
  11. drive_url is null when no drive block exists.
  12. human_edited change_action path via PATCH.
  13. co_developed change_action path via PATCH.
  14. PATCH rejects unknown change_action with 400.
  15. get_hitl_kind / set_hitl_kind helper unit tests.

Test style mirrors test_deliverable_hitl.py / test_deliverable_pipeline.py:
  - ``client`` fixture for SessionLocal monkeypatching
  - ``owner_token`` fixture for user setup
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
from app.enums import DELIVERABLE_ACCEPT_WORKFLOW

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def auth_h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class _Resp:
    """Minimal httpx-like response for monkeypatching _call_codev_agent."""

    def __init__(self, status_code: int = 200, body: dict | str | None = None) -> None:
        self.status_code = status_code
        if body is None:
            body = {"response": '{"summary": "AI proposed revision", "step_key": "codev_result"}'}
        if isinstance(body, dict):
            import json
            self._text = json.dumps(body)
        else:
            self._text = str(body)
        self.text = self._text

    def json(self) -> dict:
        import json
        return json.loads(self._text)


async def _create_deliverable_at_status(
    session_maker,
    uid: str,
    status: str,
    content: dict | None = None,
    meta: dict | None = None,
    deliverable_type: str = "cost_estimate",
) -> Deliverable:
    """Create a deliverable directly in DB and set its status."""
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
            title=f"Test deliverable ({deliverable_type})",
            content=content or {"summary": "initial content", "step_key": "scope_draft"},
        )
        if status != "draft" or meta:
            row = await append_deliverable_version_service(
                s,
                row,
                status=status,
                meta=meta,
                change_action="updated",
            )
        deliverable_id = row.id
        version = row.version
        return row


async def _fetch_deliverable(session_maker, deliverable_id: str) -> Deliverable:
    async with session_maker() as s:
        row = await s.get(Deliverable, deliverable_id)
        return row


async def _get_versions(session_maker, deliverable_id: str) -> list[DeliverableVersion]:
    async with session_maker() as s:
        rows = (
            await s.execute(
                select(DeliverableVersion)
                .where(DeliverableVersion.deliverable_id == deliverable_id)
                .order_by(DeliverableVersion.version.asc())
            )
        ).scalars().all()
        return list(rows)


async def _get_approvals_for_workflow(session_maker, workflow: str) -> list[ApprovalItem]:
    async with session_maker() as s:
        rows = (
            await s.execute(
                select(ApprovalItem).where(ApprovalItem.workflow == workflow)
            )
        ).scalars().all()
        return list(rows)


# ---------------------------------------------------------------------------
# Test 1: codev returns proposed content WITHOUT committing
# ---------------------------------------------------------------------------


async def test_codev_returns_proposed_without_committing(
    client, owner_token, session_maker, monkeypatch
):
    """codev returns proposed_content, based_on_version, proposed_summary — NO
    version bump, NO status change, NO new DeliverableVersion row."""
    import app.routes.deliverables as delmod

    uid, tok = owner_token
    row = await _create_deliverable_at_status(session_maker, uid, "awaiting_human")
    initial_version = row.version
    initial_status = row.status
    deliverable_id = row.id

    async def _fake_adk(*a, **k):
        import json
        return _Resp(200, {"response": json.dumps({"summary": "AI improved version", "items": [1, 2, 3]})})

    monkeypatch.setattr(delmod, "_call_codev_agent", _fake_adk)

    r = await client.post(
        f"/v1/deliverables/{deliverable_id}/codev",
        json={"prompt": "Add more line items to the estimate"},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()

    # Response shape check.
    assert "proposed_content" in body
    assert "based_on_version" in body
    assert body["based_on_version"] == initial_version

    # CRITICAL: version and status must be UNCHANGED.
    refreshed = await _fetch_deliverable(session_maker, deliverable_id)
    assert refreshed.version == initial_version, (
        f"codev must not bump version: before={initial_version}, after={refreshed.version}"
    )
    assert refreshed.status == initial_status, (
        f"codev must not change status: before={initial_status!r}, after={refreshed.status!r}"
    )

    # No extra DeliverableVersion rows from the codev call itself.
    versions_before_count = initial_version  # each version has a snapshot row
    versions_after = await _get_versions(session_maker, deliverable_id)
    assert len(versions_after) == initial_version, (
        f"codev must not append a version snapshot: expected {initial_version} rows, "
        f"got {len(versions_after)}"
    )


# ---------------------------------------------------------------------------
# Test 2: codev accept via resume commits exactly ONE new version
# ---------------------------------------------------------------------------


async def test_resume_commits_one_version_co_developed(
    client, owner_token, session_maker, monkeypatch
):
    """Accepting a co-dev proposal via /resume commits exactly one new version
    with change_action='co_developed' and moves off awaiting_human."""
    import app.routes.deliverables as delmod

    uid, tok = owner_token
    row = await _create_deliverable_at_status(session_maker, uid, "awaiting_human")
    initial_version = row.version
    deliverable_id = row.id

    versions_before = await _get_versions(session_maker, deliverable_id)

    accepted_content = {"summary": "Human-accepted AI content", "finalized": True}
    r = await client.post(
        f"/v1/deliverables/{deliverable_id}/resume",
        json={"content": accepted_content, "resume_chain": False},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, f"resume failed: {r.text}"
    body = r.json()

    # Version must have bumped by exactly 1.
    assert body["version"] == initial_version + 1, (
        f"Expected version {initial_version + 1}, got {body['version']}"
    )

    # Status must be 'approved' (resume_chain=False).
    assert body["status"] == "approved", f"Expected 'approved', got {body['status']!r}"

    # Exactly one new DeliverableVersion row appended.
    versions_after = await _get_versions(session_maker, deliverable_id)
    assert len(versions_after) == len(versions_before) + 1, (
        f"Expected exactly 1 new version row; before={len(versions_before)}, "
        f"after={len(versions_after)}"
    )

    # The new snapshot must have change_action='co_developed'.
    new_snap = versions_after[-1]
    assert new_snap.change_action == "co_developed", (
        f"Expected change_action='co_developed', got {new_snap.change_action!r}"
    )

    # Content must reflect what was submitted.
    refreshed = await _fetch_deliverable(session_maker, deliverable_id)
    assert refreshed.content == accepted_content


# ---------------------------------------------------------------------------
# Test 3: resume with resume_chain=True → 'in_progress' (documents limitation)
# ---------------------------------------------------------------------------


async def test_resume_with_resume_chain_true_sets_in_progress(
    client, owner_token, session_maker
):
    """resume_chain=True transitions status to 'in_progress' (chain can continue).
    Mid-chain auto-resume is a Phase G4 deferred item; this test documents it."""
    uid, tok = owner_token
    row = await _create_deliverable_at_status(session_maker, uid, "awaiting_human")
    deliverable_id = row.id

    accepted_content = {"summary": "Continuing the chain", "phase": "in_progress"}
    r = await client.post(
        f"/v1/deliverables/{deliverable_id}/resume",
        json={"content": accepted_content, "resume_chain": True},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, f"resume failed: {r.text}"
    body = r.json()

    # Status must be 'in_progress' when resume_chain=True.
    assert body["status"] == "in_progress", (
        f"Expected 'in_progress', got {body['status']!r}"
    )
    # change_action must be 'co_developed'.
    refreshed_versions = await _get_versions(session_maker, deliverable_id)
    last_snap = refreshed_versions[-1]
    assert last_snap.change_action == "co_developed"

    # DOCUMENTED LIMITATION: mid-chain auto-resume is deferred to Phase G4.
    # The deliverable is at 'in_progress' but the chain has NOT been re-invoked.
    # Caller must trigger a new chain run if they want downstream steps to run.


# ---------------------------------------------------------------------------
# Test 4: resume with resume_chain=False → 'approved'
# ---------------------------------------------------------------------------


async def test_resume_without_chain_sets_approved(
    client, owner_token, session_maker
):
    """resume_chain=False transitions status to 'approved' (human done; no chain)."""
    uid, tok = owner_token
    row = await _create_deliverable_at_status(session_maker, uid, "awaiting_human")
    deliverable_id = row.id

    r = await client.post(
        f"/v1/deliverables/{deliverable_id}/resume",
        json={"content": {"summary": "Final approved content"}, "resume_chain": False},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, f"resume failed: {r.text}"
    body = r.json()
    assert body["status"] == "approved", f"Expected 'approved', got {body['status']!r}"


# ---------------------------------------------------------------------------
# Test 5: ADK transport failure in codev → 502, live deliverable untouched
# ---------------------------------------------------------------------------


async def test_codev_adk_transport_failure_returns_502_and_leaves_deliverable(
    client, owner_token, session_maker, monkeypatch
):
    """If the ADK call raises a transport error, /codev returns 502 and the
    live deliverable is completely untouched (same version, same content)."""
    import app.routes.deliverables as delmod

    uid, tok = owner_token
    original_content = {"summary": "original untouched content", "items": []}
    row = await _create_deliverable_at_status(
        session_maker, uid, "awaiting_human", content=original_content
    )
    deliverable_id = row.id
    initial_version = row.version

    async def _fail_adk(*a, **k):
        raise ConnectionError("simulated network failure")

    monkeypatch.setattr(delmod, "_call_codev_agent", _fail_adk)

    r = await client.post(
        f"/v1/deliverables/{deliverable_id}/codev",
        json={"prompt": "Improve the estimate"},
        headers=auth_h(tok),
    )
    assert r.status_code == 502, f"Expected 502, got {r.status_code}: {r.text}"
    assert "Agent call failed" in r.json().get("detail", ""), (
        f"Expected 'Agent call failed' in detail: {r.json()}"
    )

    # CRITICAL: deliverable must be byte-for-byte untouched.
    refreshed = await _fetch_deliverable(session_maker, deliverable_id)
    assert refreshed.version == initial_version, (
        f"Version changed after 502: {initial_version} → {refreshed.version}"
    )
    assert refreshed.content == original_content, (
        f"Content changed after 502: {refreshed.content!r}"
    )
    assert refreshed.status == "awaiting_human"


# ---------------------------------------------------------------------------
# Test 6: ADK non-200 status in codev → 502, live deliverable untouched
# ---------------------------------------------------------------------------


async def test_codev_adk_bad_status_returns_502(
    client, owner_token, session_maker, monkeypatch
):
    """If ADK returns a non-200 response, /codev returns 502 and leaves the
    deliverable untouched."""
    import app.routes.deliverables as delmod

    uid, tok = owner_token
    original_content = {"summary": "safe content"}
    row = await _create_deliverable_at_status(
        session_maker, uid, "in_progress", content=original_content
    )
    deliverable_id = row.id
    initial_version = row.version

    async def _bad_adk(*a, **k):
        return _Resp(500, "internal server error")

    monkeypatch.setattr(delmod, "_call_codev_agent", _bad_adk)

    r = await client.post(
        f"/v1/deliverables/{deliverable_id}/codev",
        json={"prompt": "Propose a revision"},
        headers=auth_h(tok),
    )
    assert r.status_code == 502, f"Expected 502, got {r.status_code}: {r.text}"

    refreshed = await _fetch_deliverable(session_maker, deliverable_id)
    assert refreshed.version == initial_version
    assert refreshed.content == original_content


# ---------------------------------------------------------------------------
# Test 7: hitl_kind=co_development gate → NO ApprovalItem created
# ---------------------------------------------------------------------------


async def test_co_development_gate_does_not_create_approval_item(
    client, owner_token, session_maker
):
    """A deliverable with hitl_kind='co_development' must NOT produce an
    ApprovalItem when create_deliverable_approval is called."""
    from app.services.deliverable_hitl import (
        create_deliverable_approval,
        set_hitl_kind,
        HITL_KIND_CO_DEVELOPMENT,
    )

    uid, tok = owner_token
    meta_with_kind = set_hitl_kind(None, HITL_KIND_CO_DEVELOPMENT)
    row = await _create_deliverable_at_status(
        session_maker, uid, "awaiting_human", meta=meta_with_kind
    )
    deliverable_id = row.id

    approvals_before = await _get_approvals_for_workflow(
        session_maker, DELIVERABLE_ACCEPT_WORKFLOW
    )

    # Call create_deliverable_approval directly — must return None, no item.
    async with session_maker() as s:
        live_row = await s.get(Deliverable, deliverable_id)
        result = await create_deliverable_approval(
            s, live_row, actor=uid, summary="Co-dev gate summary"
        )

    assert result is None, (
        f"Expected None for co_development gate, got {result!r}"
    )

    approvals_after = await _get_approvals_for_workflow(
        session_maker, DELIVERABLE_ACCEPT_WORKFLOW
    )
    assert len(approvals_after) == len(approvals_before), (
        f"Expected no new ApprovalItem for co_development gate; "
        f"before={len(approvals_before)}, after={len(approvals_after)}"
    )


# ---------------------------------------------------------------------------
# Test 8: hitl_kind=decision gate → ApprovalItem IS created (existing behavior)
# ---------------------------------------------------------------------------


async def test_decision_gate_still_creates_approval_item(
    client, owner_token, session_maker
):
    """A deliverable with hitl_kind='decision' (or unset, defaulting to decision)
    must create an ApprovalItem — existing Phase D behavior unchanged."""
    from app.services.deliverable_hitl import (
        create_deliverable_approval,
        set_hitl_kind,
        HITL_KIND_DECISION,
    )
    from app.enums import Lane

    uid, tok = owner_token
    meta_with_kind = set_hitl_kind(None, HITL_KIND_DECISION)
    row = await _create_deliverable_at_status(
        session_maker, uid, "awaiting_human", meta=meta_with_kind
    )
    deliverable_id = row.id

    approvals_before = await _get_approvals_for_workflow(
        session_maker, DELIVERABLE_ACCEPT_WORKFLOW
    )

    async with session_maker() as s:
        live_row = await s.get(Deliverable, deliverable_id)
        result = await create_deliverable_approval(
            s, live_row, actor=uid, summary="Decision gate"
        )

    assert result is not None, "Expected an ApprovalItem for decision gate"
    assert result.workflow == DELIVERABLE_ACCEPT_WORKFLOW
    assert result.lane == Lane.SINGLE.value

    approvals_after = await _get_approvals_for_workflow(
        session_maker, DELIVERABLE_ACCEPT_WORKFLOW
    )
    assert len(approvals_after) == len(approvals_before) + 1, (
        f"Expected 1 new ApprovalItem for decision gate"
    )


# ---------------------------------------------------------------------------
# Test 9: drive_url surfaced from content drive block
# ---------------------------------------------------------------------------


async def test_drive_url_surfaced_from_content(
    client, owner_token, session_maker
):
    """_deliverable_out surfaces drive_url from the content.drive.url field."""
    uid, tok = owner_token
    content_with_drive = {
        "summary": "drive-authored doc",
        "drive": {
            "mode": "doc",
            "url": "https://docs.google.com/document/d/abc123/edit",
            "doc_id": "abc123",
        },
    }
    row = await _create_deliverable_at_status(
        session_maker, uid, "approved", content=content_with_drive
    )

    r = await client.get(
        f"/v1/deliverables/{row.id}",
        headers=auth_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert "drive_url" in body, f"drive_url field missing from response: {list(body.keys())}"
    assert body["drive_url"] == "https://docs.google.com/document/d/abc123/edit", (
        f"Unexpected drive_url: {body['drive_url']!r}"
    )


# ---------------------------------------------------------------------------
# Test 10: drive_url surfaced from meta drive block
# ---------------------------------------------------------------------------


async def test_drive_url_surfaced_from_meta(
    client, owner_token, session_maker
):
    """_deliverable_out surfaces drive_url from meta.drive.url when not in content."""
    uid, tok = owner_token
    meta_with_drive = {
        "drive": {
            "mode": "sheet",
            "url": "https://docs.google.com/spreadsheets/d/xyz789/edit",
            "sheet_id": "xyz789",
        },
    }
    row = await _create_deliverable_at_status(
        session_maker, uid, "approved",
        content={"summary": "no drive block here"},
        meta=meta_with_drive,
    )

    r = await client.get(
        f"/v1/deliverables/{row.id}",
        headers=auth_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("drive_url") == "https://docs.google.com/spreadsheets/d/xyz789/edit", (
        f"Unexpected drive_url from meta: {body.get('drive_url')!r}"
    )


# ---------------------------------------------------------------------------
# Test 11: drive_url is null when no drive block exists
# ---------------------------------------------------------------------------


async def test_drive_url_is_null_when_no_drive_block(
    client, owner_token, session_maker
):
    """_deliverable_out returns drive_url=null when neither content nor meta has
    a drive block."""
    uid, tok = owner_token
    row = await _create_deliverable_at_status(
        session_maker, uid, "approved",
        content={"summary": "no drive"},
    )

    r = await client.get(
        f"/v1/deliverables/{row.id}",
        headers=auth_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("drive_url") is None, (
        f"Expected drive_url=null, got {body.get('drive_url')!r}"
    )


# ---------------------------------------------------------------------------
# Test 12: human_edited change_action via PATCH
# ---------------------------------------------------------------------------


async def test_patch_human_edited_change_action(
    client, owner_token, session_maker
):
    """PATCH with change_action='human_edited' creates a version snapshot with
    that action recorded, making the edit auditable."""
    uid, tok = owner_token
    row = await _create_deliverable_at_status(session_maker, uid, "in_progress")
    deliverable_id = row.id
    initial_version = row.version

    new_content = {"summary": "Human manually revised this", "human_note": "Adjusted scope"}
    r = await client.patch(
        f"/v1/deliverables/{deliverable_id}",
        json={"content": new_content, "change_action": "human_edited"},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, f"PATCH failed: {r.text}"
    body = r.json()
    assert body["version"] == initial_version + 1

    versions = await _get_versions(session_maker, deliverable_id)
    last_snap = versions[-1]
    assert last_snap.change_action == "human_edited", (
        f"Expected change_action='human_edited', got {last_snap.change_action!r}"
    )


# ---------------------------------------------------------------------------
# Test 13: co_developed change_action via PATCH
# ---------------------------------------------------------------------------


async def test_patch_co_developed_change_action(
    client, owner_token, session_maker
):
    """PATCH with change_action='co_developed' is valid and records the action."""
    uid, tok = owner_token
    row = await _create_deliverable_at_status(session_maker, uid, "awaiting_human")
    deliverable_id = row.id

    r = await client.patch(
        f"/v1/deliverables/{deliverable_id}",
        json={
            "content": {"summary": "Accepted co-dev content"},
            "status": "approved",
            "change_action": "co_developed",
        },
        headers=auth_h(tok),
    )
    assert r.status_code == 200, f"PATCH failed: {r.text}"
    body = r.json()
    assert body["status"] == "approved"

    versions = await _get_versions(session_maker, deliverable_id)
    last_snap = versions[-1]
    assert last_snap.change_action == "co_developed"


# ---------------------------------------------------------------------------
# Test 14: PATCH rejects unknown change_action with 400
# ---------------------------------------------------------------------------


async def test_patch_rejects_invalid_change_action(
    client, owner_token, session_maker
):
    """PATCH with an unknown change_action returns 400 and leaves the deliverable
    untouched."""
    uid, tok = owner_token
    row = await _create_deliverable_at_status(session_maker, uid, "in_progress")
    deliverable_id = row.id
    initial_version = row.version

    r = await client.patch(
        f"/v1/deliverables/{deliverable_id}",
        json={"content": {"summary": "hacked"}, "change_action": "self_approved"},
        headers=auth_h(tok),
    )
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
    assert "change_action" in r.json().get("detail", "").lower(), (
        f"Expected error message to mention change_action: {r.json()}"
    )

    # Deliverable must be untouched.
    refreshed = await _fetch_deliverable(session_maker, deliverable_id)
    assert refreshed.version == initial_version


# ---------------------------------------------------------------------------
# Test 15: get_hitl_kind / set_hitl_kind helper unit tests
# ---------------------------------------------------------------------------


async def test_hitl_kind_helpers(client, owner_token, session_maker):
    """Unit test for get_hitl_kind and set_hitl_kind helpers."""
    from app.services.deliverable_hitl import (
        get_hitl_kind,
        set_hitl_kind,
        HITL_KIND_DECISION,
        HITL_KIND_CO_DEVELOPMENT,
    )

    uid, _ = owner_token

    # --- set_hitl_kind ---

    # Setting co_development
    meta = set_hitl_kind(None, HITL_KIND_CO_DEVELOPMENT)
    assert meta["hitl_kind"] == HITL_KIND_CO_DEVELOPMENT

    # Setting decision
    meta2 = set_hitl_kind({"existing_field": 42}, HITL_KIND_DECISION)
    assert meta2["hitl_kind"] == HITL_KIND_DECISION
    assert meta2["existing_field"] == 42  # original fields preserved

    # Original dict not mutated
    original = {"a": 1}
    _ = set_hitl_kind(original, HITL_KIND_CO_DEVELOPMENT)
    assert "hitl_kind" not in original, "set_hitl_kind must not mutate the original dict"

    # Invalid kind raises ValueError
    try:
        set_hitl_kind(None, "invalid_kind")
        assert False, "Expected ValueError for invalid kind"
    except ValueError as e:
        assert "hitl_kind" in str(e).lower() or "invalid_kind" in str(e)

    # --- get_hitl_kind ---

    # Create deliverables with different meta states.
    row_no_kind = await _create_deliverable_at_status(session_maker, uid, "awaiting_human")
    row_decision = await _create_deliverable_at_status(
        session_maker, uid, "awaiting_human",
        meta=set_hitl_kind(None, HITL_KIND_DECISION)
    )
    row_codev = await _create_deliverable_at_status(
        session_maker, uid, "awaiting_human",
        meta=set_hitl_kind(None, HITL_KIND_CO_DEVELOPMENT)
    )

    async with session_maker() as s:
        live_no_kind = await s.get(Deliverable, row_no_kind.id)
        live_decision = await s.get(Deliverable, row_decision.id)
        live_codev = await s.get(Deliverable, row_codev.id)

    # No hitl_kind → defaults to "decision" (backward compat).
    assert get_hitl_kind(live_no_kind) == HITL_KIND_DECISION, (
        f"Expected default 'decision', got {get_hitl_kind(live_no_kind)!r}"
    )
    assert get_hitl_kind(live_decision) == HITL_KIND_DECISION
    assert get_hitl_kind(live_codev) == HITL_KIND_CO_DEVELOPMENT
