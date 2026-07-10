"""Phase B — deliverable producer tests.

When a piloted intent's request completes, a tracked Deliverable is produced
from the agent output. Non-piloted intents produce nothing; a deliverable-
creation failure must not fail the request (fail-safe).

These use the `client` fixture because it monkeypatches app.db.SessionLocal to
the in-memory test session maker — which is the session maker the background
producer (`_dispatch_to_agent`) opens internally. Without the client fixture,
SessionLocal points at the real DB and the tables don't exist.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

# Import models at top level so create_all registers them (conftest quirk).
import app.routes.requests  # noqa: F401
from app.deliverable_registry import INTENT_TO_DELIVERABLE
from app.models_deliverables import Deliverable, DeliverableVersion
from app.models_requests import RequestRecord

pytestmark = pytest.mark.asyncio


class _Resp:
    status_code = 200
    text = "agent produced this"

    def json(self):
        return {"response": "agent produced this"}


async def _seed_and_dispatch(client, monkeypatch, uid, intent, message):
    """Seed a processing request via the patched SessionLocal, then run the
    real producer path with the ADK call mocked to a successful completion."""
    import app.db as db_module
    import app.routes.requests as reqmod

    async with db_module.SessionLocal() as s:
        rec = RequestRecord(user_id=uid, message=message, intent=intent, status="processing")
        s.add(rec)
        await s.commit()
        await s.refresh(rec)
        rid = rec.id

    async def _fake_adk(*a, **k):
        return _Resp()

    monkeypatch.setattr(reqmod, "_call_adk_with_retry", _fake_adk)
    await reqmod._dispatch_to_agent(
        request_id=rid, intent=intent, message=message,
        filenames=[], drive_url=None, user_id=uid,
    )
    return rid


async def _deliverables_for(uid):
    import app.db as db_module
    async with db_module.SessionLocal() as s:
        rows = (
            await s.execute(select(Deliverable).where(Deliverable.user_id == uid))
        ).scalars().all()
        return list(rows)


async def test_estimate_intent_produces_cost_estimate(client, owner_token, monkeypatch):
    uid, _ = owner_token
    await _seed_and_dispatch(client, monkeypatch, uid, "estimate", "Price 200 LF trench")
    dels = await _deliverables_for(uid)
    assert len(dels) == 1
    assert dels[0].deliverable_type == "cost_estimate"
    assert dels[0].module_key == "estimates"
    # Phase C: chain produces >=1 version (v1 from step A, v2+ from subsequent steps)
    assert dels[0].version >= 1


async def test_rfi_intent_produces_rfi_response(client, owner_token, monkeypatch):
    uid, _ = owner_token
    await _seed_and_dispatch(client, monkeypatch, uid, "rfi", "Clarify slab spec")
    dels = await _deliverables_for(uid)
    assert len(dels) == 1
    assert dels[0].deliverable_type == "rfi_response"
    assert dels[0].module_key == "projects"


async def test_non_piloted_intent_produces_nothing(client, owner_token, monkeypatch):
    uid, _ = owner_token
    assert "contract" not in INTENT_TO_DELIVERABLE
    await _seed_and_dispatch(client, monkeypatch, uid, "contract", "Review CO #12")
    assert await _deliverables_for(uid) == []


async def test_produced_deliverable_has_single_created_snapshot(client, owner_token, monkeypatch):
    """Phase C: v1 snapshot (change_action='created') always exists; chain may add more.
    The v1 'created' snapshot contract is preserved by Phase A; Phase C appends 'updated'
    snapshots for subsequent steps.
    """
    import app.db as db_module
    uid, _ = owner_token
    await _seed_and_dispatch(client, monkeypatch, uid, "estimate", "Budget check")
    dels = await _deliverables_for(uid)
    async with db_module.SessionLocal() as s:
        snaps = (
            await s.execute(
                select(DeliverableVersion).where(
                    DeliverableVersion.deliverable_id == dels[0].id
                ).order_by(DeliverableVersion.version.asc())
            )
        ).scalars().all()
    # Phase A contract: v1 'created' snapshot always exists
    assert snaps[0].version == 1 and snaps[0].change_action == "created"
    # Phase C: subsequent chain steps append 'updated' snapshots
    assert len(snaps) >= 1  # at minimum the v1 created snapshot


async def test_deliverable_failure_does_not_fail_request(client, owner_token, monkeypatch):
    """Fail-safe: if deliverable pipeline raises entirely, the request still completes.

    Phase C note: The fail-safe is implemented in requests.py which wraps
    run_deliverable_chain in a broad try/except. We patch run_deliverable_chain
    in the pipeline module to simulate a total pipeline failure.
    """
    import app.db as db_module
    import app.deliverable_pipeline as pipeline_mod

    uid, _ = owner_token

    async def _boom(*a, **k):
        raise RuntimeError("simulated deliverable failure")

    monkeypatch.setattr(pipeline_mod, "create_deliverable_service", _boom)
    rid = await _seed_and_dispatch(client, monkeypatch, uid, "estimate", "Will still complete")

    async with db_module.SessionLocal() as s:
        rec = await s.get(RequestRecord, rid)
    assert rec.status == "complete"          # request finished fine despite the failure
    assert await _deliverables_for(uid) == []  # no deliverable, but no crash
