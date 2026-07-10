"""Phase H — per-project Drive subfolder pipeline tests.

Verifies that the api-side deliverable pipeline correctly:
  1. Passes drive_subfolder (project name) in the invoke payload when a
     project_id is present (with a mocked project lookup).
  2. Omits drive_subfolder from the payload when project_id is None
     (flat-root fallback, backward-compatible with Phase C).
  3. Full integration path: _dispatch_to_agent with project_id set causes
     the deliverable chain's call_agent to include drive_subfolder.
  4. Project lookup failure degrades gracefully (no crash, no subfolder).

All ADK HTTP calls are mocked — no live network required.
Test uses the ``client`` fixture for SessionLocal patching.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

import app.routes.requests  # noqa: F401 — ensures SessionLocal patch applies
import app.models_projects  # noqa: F401 — ensures 'projects' table in metadata
from app.models_requests import RequestRecord

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_deliverable_pipeline.py pattern)
# ---------------------------------------------------------------------------


class _Resp:
    """Mock HTTP response returned by the patched _call_adk_with_retry."""

    def __init__(self, text: str = "agent output") -> None:
        self.status_code = 200
        self.text = text

    def json(self) -> dict:
        return {"response": self.text}


async def _seed_request(uid: str, intent: str, message: str) -> str:
    """Insert a processing request row and return its id."""
    import app.db as db_module

    async with db_module.SessionLocal() as s:
        rec = RequestRecord(user_id=uid, message=message, intent=intent, status="processing")
        s.add(rec)
        await s.commit()
        await s.refresh(rec)
        return rec.id


# ---------------------------------------------------------------------------
# Test: invoke payload includes drive_subfolder when project_id is set
# ---------------------------------------------------------------------------


async def test_invoke_payload_includes_subfolder_when_project_linked(
    client, owner_token, monkeypatch
):
    """When project_id is set and the project has a name, the _call_agent_for_pipeline
    helper includes drive_subfolder in the ADK invoke payload."""
    import app.db as db_module
    import app.routes.requests as reqmod
    from app.models_projects import Project

    uid, _ = owner_token

    # Seed a project so the lookup finds it.
    async with db_module.SessionLocal() as s:
        proj = Project(user_id=uid, name="Acme Bridge Tower")
        s.add(proj)
        await s.commit()
        await s.refresh(proj)
        project_id = proj.id

    rid = await _seed_request(uid, "estimate", "Price the steel scope")

    # Capture the adk payload sent for each chain call.
    captured_payloads: list[dict] = []
    call_count = [0]
    responses = ["Scope draft output", "Unit pricing output"]

    async def _capture_adk(endpoint, payload, agent_name, request_id):
        captured_payloads.append(dict(payload))
        idx = call_count[0]
        call_count[0] += 1
        return _Resp(responses[idx] if idx < len(responses) else responses[-1])

    monkeypatch.setattr(reqmod, "_call_adk_with_retry", _capture_adk)

    await reqmod._dispatch_to_agent(
        request_id=rid,
        intent="estimate",
        message="Price the steel scope",
        filenames=[],
        drive_url=None,
        user_id=uid,
        project_id=project_id,
    )

    # All chain calls should include drive_subfolder = project name
    assert len(captured_payloads) >= 2, (
        f"Expected >=2 ADK calls (chain steps), got {len(captured_payloads)}"
    )
    for pl in captured_payloads:
        assert pl.get("drive_subfolder") == "Acme Bridge Tower", (
            f"Expected drive_subfolder='Acme Bridge Tower' in payload, got: {pl}"
        )


# ---------------------------------------------------------------------------
# Test: invoke payload omits drive_subfolder when project_id is None
# ---------------------------------------------------------------------------


async def test_invoke_payload_omits_subfolder_when_no_project(
    client, owner_token, monkeypatch
):
    """When project_id is None, the ADK invoke payload has no drive_subfolder
    (backward-compatible flat-root behavior from Phase C)."""
    import app.routes.requests as reqmod

    uid, _ = owner_token
    rid = await _seed_request(uid, "estimate", "General estimate request")

    captured_payloads: list[dict] = []
    call_count = [0]
    responses = ["Step A output", "Step B output"]

    async def _capture_adk(endpoint, payload, agent_name, request_id):
        captured_payloads.append(dict(payload))
        idx = call_count[0]
        call_count[0] += 1
        return _Resp(responses[idx] if idx < len(responses) else responses[-1])

    monkeypatch.setattr(reqmod, "_call_adk_with_retry", _capture_adk)

    await reqmod._dispatch_to_agent(
        request_id=rid,
        intent="estimate",
        message="General estimate request",
        filenames=[],
        drive_url=None,
        user_id=uid,
        project_id=None,  # no project
    )

    # All payloads should NOT include drive_subfolder
    assert len(captured_payloads) >= 1
    for pl in captured_payloads:
        assert "drive_subfolder" not in pl, (
            f"Unexpected drive_subfolder in payload when project_id=None: {pl}"
        )


# ---------------------------------------------------------------------------
# Test: project lookup failure degrades gracefully
# ---------------------------------------------------------------------------


async def test_project_lookup_failure_falls_back_gracefully(
    client, owner_token, monkeypatch
):
    """If the project lookup raises, the request still proceeds without subfolder
    (no crash, no drive_subfolder in payload)."""
    import app.routes.requests as reqmod
    import app.db as db_module

    uid, _ = owner_token
    rid = await _seed_request(uid, "estimate", "Estimate with bad project")

    captured_payloads: list[dict] = []
    call_count = [0]
    responses = ["Step A", "Step B"]

    async def _capture_adk(endpoint, payload, agent_name, request_id):
        captured_payloads.append(dict(payload))
        idx = call_count[0]
        call_count[0] += 1
        return _Resp(responses[idx] if idx < len(responses) else responses[-1])

    monkeypatch.setattr(reqmod, "_call_adk_with_retry", _capture_adk)

    # Patch the project lookup to raise
    original_session_local = db_module.SessionLocal

    class _FaultyContextManager:
        async def __aenter__(self):
            raise RuntimeError("DB connection error")
        async def __aexit__(self, *a):
            pass

    import unittest.mock as mock

    # Patch only when getting a project session — tricky because we can't
    # distinguish calls easily. Instead patch the Project.get() path.
    from app.models_projects import Project as _Project

    async def _bad_get(self_inner, model, pk):
        if model is _Project:
            raise RuntimeError("simulated DB error")
        return await original_session_local.__class__.__mro__[0].__aenter__(self_inner).get(model, pk)

    with mock.patch.object(_Project, "__init__", side_effect=RuntimeError("fail")):
        # Use an invalid project_id — the lookup will fail to find it but
        # that's non-raising. Use a truly invalid path via non-existent id.
        pass

    # Simpler: patch the inner session get to raise for Project
    import contextlib
    from sqlalchemy.ext.asyncio import AsyncSession

    original_get = AsyncSession.get

    async def _patched_get(self_inner, model, pk, **kwargs):
        if model is _Project:
            raise RuntimeError("simulated project DB error")
        return await original_get(self_inner, model, pk, **kwargs)

    with mock.patch.object(AsyncSession, "get", _patched_get):
        await reqmod._dispatch_to_agent(
            request_id=rid,
            intent="estimate",
            message="Estimate with bad project",
            filenames=[],
            drive_url=None,
            user_id=uid,
            project_id="some-project-id",  # will fail the lookup
        )

    # Must have proceeded despite lookup failure
    assert len(captured_payloads) >= 1, "Expected at least 1 ADK call (chain ran despite error)"
    # No drive_subfolder in payload (graceful degradation)
    for pl in captured_payloads:
        assert "drive_subfolder" not in pl, (
            f"Unexpected drive_subfolder after lookup failure: {pl}"
        )


# ---------------------------------------------------------------------------
# Test: project_id passed through to run_deliverable_chain
# ---------------------------------------------------------------------------


async def test_project_id_threaded_to_deliverable_chain(client, owner_token, monkeypatch):
    """When project_id is provided, it is passed to run_deliverable_chain
    (not hardcoded as None)."""
    import app.db as db_module
    import app.routes.requests as reqmod
    from app.models_projects import Project
    from app.deliverable_pipeline import run_deliverable_chain

    uid, _ = owner_token

    # Create a project
    async with db_module.SessionLocal() as s:
        proj = Project(user_id=uid, name="Integration Test Project")
        s.add(proj)
        await s.commit()
        await s.refresh(proj)
        pid = proj.id

    rid = await _seed_request(uid, "estimate", "Estimate with project")

    chain_calls: list[dict] = []

    async def _fake_chain(db, *, user_id, project_id, deliverable_type, seed_message, call_agent, **kw):
        chain_calls.append({
            "user_id": user_id,
            "project_id": project_id,
        })
        return None  # simulate chain producing nothing

    async def _noop_adk(*a, **k):
        return _Resp("ok")

    monkeypatch.setattr(reqmod, "_call_adk_with_retry", _noop_adk)
    monkeypatch.setattr(reqmod, "run_deliverable_chain", _fake_chain)

    await reqmod._dispatch_to_agent(
        request_id=rid,
        intent="estimate",
        message="Estimate with project",
        filenames=[],
        drive_url=None,
        user_id=uid,
        project_id=pid,
    )

    assert len(chain_calls) == 1, f"Expected 1 chain call, got {chain_calls}"
    assert chain_calls[0]["project_id"] == pid, (
        f"Expected project_id={pid!r} in chain call, got {chain_calls[0]!r}"
    )
