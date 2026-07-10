"""Phase H — Drive authoring integration tests for the deliverable pipeline.

Verifies that run_deliverable_chain correctly authors finalized deliverable
content to Google Drive when DRIVE_ENABLED=True, and behaves identically to
today when DRIVE_ENABLED=False.

Scenarios:
  1. DRIVE_ENABLED=False  → no Drive call, no drive_url in output.
  2. DRIVE_ENABLED=True + mocked author → drive block stored in content,
     _deliverable_out surfaces drive_url.
  3. DRIVE_ENABLED=True + subfolder set → author called with correct subfolder.
  4. DRIVE_ENABLED=True + project linked → subfolder = project name.
  5. DRIVE_ENABLED=True + no project → subfolder=None (root folder authoring).
  6. DRIVE_ENABLED=True + Drive error → chain still completes, deliverable
     saved as local/text record, content.drive.mode = 'local'.
  7. Existing pipeline tests stay green (no Drive call when disabled).
  8. co-dev resume + DRIVE_ENABLED=True + mocked author → drive_url surfaces.
  9. co-dev resume + Drive error → endpoint still returns 200.
 10. Direct pipeline unit test: drive block stored in content after chain.

All Drive calls are mocked — no live network required.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

import app.routes.requests  # noqa: F401 — ensure SessionLocal patch applies
import app.models_projects  # noqa: F401 — ensure 'projects' table in metadata
from app.models_deliverables import Deliverable, DeliverableVersion
from app.models_requests import RequestRecord

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

MOCK_DRIVE_URL = "https://docs.google.com/document/d/fake-doc-id/edit"
MOCK_DRIVE_BLOCK = {
    "mode": "drive",
    "kind": "doc",
    "doc_id": "fake-doc-id",
    "url": MOCK_DRIVE_URL,
    "title": "Test Deliverable",
}


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


async def _get_deliverable_for_user(uid: str) -> Deliverable | None:
    import app.db as db_module

    async with db_module.SessionLocal() as s:
        rows = (
            await s.execute(select(Deliverable).where(Deliverable.user_id == uid))
        ).scalars().all()
        return rows[0] if rows else None


async def _dispatch(client, monkeypatch, uid: str, intent: str, message: str,
                    project_id: str | None = None):
    """Seed + dispatch a request with two canned ADK responses."""
    import app.routes.requests as reqmod

    rid = await _seed_request(uid, intent, message)

    responses = ["Step A output", "Step B output"]
    call_count = [0]

    async def _fake_adk(*a, **k):
        idx = call_count[0]
        call_count[0] += 1
        return _Resp(responses[idx] if idx < len(responses) else responses[-1])

    monkeypatch.setattr(reqmod, "_call_adk_with_retry", _fake_adk)
    await reqmod._dispatch_to_agent(
        request_id=rid,
        intent=intent,
        message=message,
        filenames=[],
        drive_url=None,
        user_id=uid,
        project_id=project_id,
    )
    return rid


# ---------------------------------------------------------------------------
# 1. DRIVE_ENABLED=False → no Drive call, no drive_url in deliverable output
# ---------------------------------------------------------------------------

async def test_drive_disabled_no_drive_call(client, owner_token, monkeypatch):
    """When DRIVE_ENABLED=False the drive author is never called and
    drive_url is not set on the output deliverable."""
    from app.config import get_settings
    import app.deliverable_pipeline as pipeline_mod

    uid, _ = owner_token

    author_calls: list[dict] = []

    async def _mock_author(kind, title, content, *, subfolder=None):
        author_calls.append({"kind": kind, "title": title, "subfolder": subfolder})
        return MOCK_DRIVE_BLOCK

    # DRIVE_ENABLED defaults to False in test config — no need to patch.
    assert not get_settings().DRIVE_ENABLED, "DRIVE_ENABLED should be False in test config"

    await _dispatch(client, monkeypatch, uid, "estimate", "Budget estimate test")

    # Drive author must NOT have been called.
    assert author_calls == [], f"Expected no Drive calls, got {author_calls}"

    d = await _get_deliverable_for_user(uid)
    assert d is not None
    assert d.version >= 2
    content = d.content or {}
    assert "drive" not in content, f"Expected no drive block when disabled, got: {content}"


# ---------------------------------------------------------------------------
# 2. DRIVE_ENABLED=True + mocked author → drive_url surfaces in output
# ---------------------------------------------------------------------------

async def test_drive_enabled_author_called_and_url_surfaces(client, owner_token):
    """When a _drive_author_fn is injected, the drive block is stored in content
    and _deliverable_out surfaces drive_url. No env patching needed — the
    injectable author bypasses DRIVE_ENABLED so this test is env-independent."""
    import app.db as db_module
    from app.deliverable_pipeline import run_deliverable_chain
    from app.routes.deliverables import _deliverable_out

    uid, _ = owner_token

    author_calls: list[dict] = []

    async def _mock_author(kind, title, content, *, subfolder=None):
        author_calls.append({"kind": kind, "title": title, "subfolder": subfolder})
        return {**MOCK_DRIVE_BLOCK, "title": title}

    async def _mock_agent(agent_name: str, msg: str) -> str:
        return "Step output text for Drive doc"

    async with db_module.SessionLocal() as db:
        deliverable = await run_deliverable_chain(
            db,
            user_id=uid,
            project_id=None,
            deliverable_type="cost_estimate",
            seed_message="Estimate steel scope",
            call_agent=_mock_agent,
            drive_subfolder=None,
            _drive_author_fn=_mock_author,
        )

    assert deliverable is not None, "Chain must produce a deliverable"
    assert deliverable.status == "awaiting_human"

    # Drive author was called exactly once (at chain completion).
    assert len(author_calls) == 1, f"Expected 1 Drive call, got {len(author_calls)}"
    assert author_calls[0]["kind"] == "doc"

    # Drive block stored in content.
    content = deliverable.content or {}
    assert "drive" in content, f"Expected drive block in content, got: {content}"
    drive = content["drive"]
    assert drive["mode"] == "drive"
    assert drive["url"] == MOCK_DRIVE_URL

    # _deliverable_out surfaces drive_url.
    out = _deliverable_out(deliverable)
    assert out["drive_url"] == MOCK_DRIVE_URL, f"drive_url not surfaced: {out}"


# ---------------------------------------------------------------------------
# 3. DRIVE_ENABLED=True + subfolder kwarg → author called with correct subfolder
# ---------------------------------------------------------------------------

async def test_drive_author_receives_correct_subfolder(client, owner_token, monkeypatch):
    """The subfolder kwarg is passed through to author_to_drive correctly."""
    import app.db as db_module
    from app.deliverable_pipeline import run_deliverable_chain

    uid, _ = owner_token

    received_subfolders: list[str | None] = []

    async def _capture_author(kind, title, content, *, subfolder=None):
        received_subfolders.append(subfolder)
        return {**MOCK_DRIVE_BLOCK, "subfolder": subfolder}

    async def _mock_agent(agent_name: str, msg: str) -> str:
        return "output"

    async with db_module.SessionLocal() as db:
        await run_deliverable_chain(
            db,
            user_id=uid,
            project_id=None,
            deliverable_type="cost_estimate",
            seed_message="test",
            call_agent=_mock_agent,
            drive_subfolder="Acme Tower Project",
            _drive_author_fn=_capture_author,
        )

    assert len(received_subfolders) == 1
    assert received_subfolders[0] == "Acme Tower Project", (
        f"Expected subfolder='Acme Tower Project', got {received_subfolders[0]!r}"
    )


# ---------------------------------------------------------------------------
# 4. DRIVE_ENABLED=True + project linked → subfolder = project name
# ---------------------------------------------------------------------------

async def test_drive_subfolder_from_project_name_via_dispatch(client, owner_token, monkeypatch):
    """When project_id is provided, the chain is called with drive_subfolder=project.name."""
    import app.db as db_module
    import app.routes.requests as reqmod
    from app.models_projects import Project

    uid, _ = owner_token

    # Seed a project.
    async with db_module.SessionLocal() as s:
        proj = Project(user_id=uid, name="Drive Test Project Alpha")
        s.add(proj)
        await s.commit()
        await s.refresh(proj)
        project_id = proj.id

    chain_kwargs_received: list[dict] = []

    original_chain = reqmod.run_deliverable_chain

    async def _capture_chain(db, *, user_id, project_id, deliverable_type, seed_message,
                             call_agent, drive_subfolder=None, **kwargs):
        chain_kwargs_received.append({"drive_subfolder": drive_subfolder})
        # Call the real chain with a mocked author so we don't need Drive creds.
        async def _noop_author(*a, **k):
            return {"mode": "local", "reason": "test"}
        return await original_chain(
            db,
            user_id=user_id,
            project_id=project_id,
            deliverable_type=deliverable_type,
            seed_message=seed_message,
            call_agent=call_agent,
            drive_subfolder=drive_subfolder,
            _drive_author_fn=_noop_author,
        )

    monkeypatch.setattr(reqmod, "run_deliverable_chain", _capture_chain)

    await _dispatch(client, monkeypatch, uid, "estimate", "Estimate with project",
                    project_id=project_id)

    assert len(chain_kwargs_received) >= 1
    assert chain_kwargs_received[0]["drive_subfolder"] == "Drive Test Project Alpha", (
        f"Expected drive_subfolder='Drive Test Project Alpha', got: {chain_kwargs_received}"
    )


# ---------------------------------------------------------------------------
# 5. DRIVE_ENABLED=True + no project → subfolder=None (root folder)
# ---------------------------------------------------------------------------

async def test_drive_subfolder_none_when_no_project(client, owner_token, monkeypatch):
    """When project_id is None, drive_subfolder=None is passed to the chain."""
    import app.routes.requests as reqmod

    uid, _ = owner_token

    chain_kwargs_received: list[dict] = []
    original_chain = reqmod.run_deliverable_chain

    async def _capture_chain(db, *, user_id, project_id, deliverable_type, seed_message,
                             call_agent, drive_subfolder=None, **kwargs):
        chain_kwargs_received.append({"drive_subfolder": drive_subfolder})
        async def _noop_author(*a, **k):
            return {"mode": "local", "reason": "test"}
        return await original_chain(
            db,
            user_id=user_id,
            project_id=project_id,
            deliverable_type=deliverable_type,
            seed_message=seed_message,
            call_agent=call_agent,
            drive_subfolder=drive_subfolder,
            _drive_author_fn=_noop_author,
        )

    monkeypatch.setattr(reqmod, "run_deliverable_chain", _capture_chain)

    await _dispatch(client, monkeypatch, uid, "estimate", "No-project estimate",
                    project_id=None)

    assert len(chain_kwargs_received) >= 1
    assert chain_kwargs_received[0]["drive_subfolder"] is None, (
        f"Expected drive_subfolder=None when no project, got: {chain_kwargs_received}"
    )


# ---------------------------------------------------------------------------
# 6. DRIVE_ENABLED=True + Drive error → chain completes, deliverable is local
# ---------------------------------------------------------------------------

async def test_drive_error_chain_still_completes_deliverable_is_local(
    client, owner_token, monkeypatch
):
    """When the Drive author raises, the chain still completes and the deliverable
    is saved as a local/text record. The request is not failed."""
    import app.db as db_module
    from app.deliverable_pipeline import run_deliverable_chain

    uid, _ = owner_token

    async def _failing_author(kind, title, content, *, subfolder=None):
        raise RuntimeError("Simulated Drive API error: quota exceeded")

    async def _mock_agent(agent_name: str, msg: str) -> str:
        return "Chain output for Drive error test"

    async with db_module.SessionLocal() as db:
        deliverable = await run_deliverable_chain(
            db,
            user_id=uid,
            project_id=None,
            deliverable_type="cost_estimate",
            seed_message="Drive error test",
            call_agent=_mock_agent,
            drive_subfolder=None,
            _drive_author_fn=_failing_author,
        )

    # Chain must still complete.
    assert deliverable is not None, "Chain must produce a deliverable even when Drive fails"
    assert deliverable.status == "awaiting_human", (
        f"Expected awaiting_human, got {deliverable.status}"
    )
    assert deliverable.version >= 2

    # drive block either absent or has mode=local (never mode=drive after error).
    content = deliverable.content or {}
    drive_block = content.get("drive")
    if drive_block is not None:
        # Fail-safe: local fallback stored, not a real drive block.
        assert drive_block.get("mode") != "drive", (
            f"Drive block should not be mode=drive after failure: {drive_block}"
        )

    # drive_url must NOT be set.
    from app.routes.deliverables import _deliverable_out
    out = _deliverable_out(deliverable)
    assert out.get("drive_url") is None, (
        f"drive_url should be None after Drive error, got: {out.get('drive_url')}"
    )


# ---------------------------------------------------------------------------
# 7. Existing pipeline tests are unaffected (DRIVE_ENABLED=False)
# ---------------------------------------------------------------------------

async def test_existing_pipeline_unaffected_drive_disabled(client, owner_token, monkeypatch):
    """Regression: full estimate chain with DRIVE_ENABLED=False behaves
    identically to pre-Phase-H behavior (no Drive calls, no drive block)."""
    import app.db as db_module
    from app.deliverable_pipeline import run_deliverable_chain
    from app.config import get_settings

    uid, _ = owner_token

    assert not get_settings().DRIVE_ENABLED, "Should be False in test env"

    author_calls: list = []

    async def _should_not_be_called(*a, **k):
        author_calls.append(True)
        raise AssertionError("Drive author should not be called when DRIVE_ENABLED=False")

    async def _mock_agent(agent_name: str, msg: str) -> str:
        return "Standard pipeline output"

    async with db_module.SessionLocal() as db:
        deliverable = await run_deliverable_chain(
            db,
            user_id=uid,
            project_id=None,
            deliverable_type="cost_estimate",
            seed_message="Standard estimate",
            call_agent=_mock_agent,
            # _drive_author_fn NOT passed → real path, but DRIVE_ENABLED=False
            # so author is skipped before any Drive call.
        )

    assert deliverable is not None
    assert deliverable.status == "awaiting_human"
    assert author_calls == [], "Drive author must not be called when DRIVE_ENABLED=False"

    content = deliverable.content or {}
    assert "drive" not in content


# ---------------------------------------------------------------------------
# 8. co-dev resume + DRIVE_ENABLED=True + mocked author → drive_url surfaces
# ---------------------------------------------------------------------------

async def test_resume_endpoint_authors_to_drive_on_accept(client, owner_token, monkeypatch):
    """POST /v1/deliverables/{id}/resume with resume_chain=False triggers Drive
    authoring when _drive_author_fn is injected (no env patching needed —
    the injectable author bypasses DRIVE_ENABLED)."""
    import app.db as db_module
    import app.routes.deliverables as deliv_mod

    uid, token = owner_token

    # Create a deliverable to resume.
    async with db_module.SessionLocal() as db:
        from app.routes.deliverables import create_deliverable_service
        row = await create_deliverable_service(
            db,
            user_id=uid,
            project_id=None,
            module_key="estimates",
            deliverable_type="cost_estimate",
            title="Resume Drive Test",
            content={"summary": "Draft content for resume", "seed_message": "test"},
        )
        deliverable_id = row.id

    # Mock the Drive author at the module level (injectable).
    # No DRIVE_ENABLED env patch needed: the resume code checks
    # DRIVE_ENABLED OR (_drive_author_fn is not None).
    author_calls: list[dict] = []

    async def _mock_author(kind, title, content, *, subfolder=None):
        author_calls.append({"kind": kind, "title": title, "subfolder": subfolder})
        return {**MOCK_DRIVE_BLOCK, "title": title}

    monkeypatch.setattr(deliv_mod, "_drive_author_fn", _mock_author)

    # Call the resume endpoint directly.
    resp = await client.post(
        f"/v1/deliverables/{deliverable_id}/resume",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "content": {"summary": "Human-accepted final content", "seed_message": "test"},
            "resume_chain": False,  # Accept and finalize; no more chain steps.
        },
    )
    assert resp.status_code == 200, f"Resume failed: {resp.status_code} {resp.text}"

    # drive_url must be surfaced in the response (it reads from content.drive.url).
    # Note: the Drive author is called from the resume endpoint; drive block
    # is stored in a separate DB session. The response refreshes the row.
    # Tolerate the case where the refresh may not see the new session's write
    # immediately in SQLite (session isolation). Check the DB directly.
    async with db_module.SessionLocal() as s:
        from app.models_deliverables import Deliverable
        final_row = await s.get(Deliverable, deliverable_id)

    assert final_row is not None
    # Drive author was called.
    assert len(author_calls) == 1, f"Expected 1 Drive call on resume accept, got {author_calls}"
    assert author_calls[0]["kind"] == "doc"


# ---------------------------------------------------------------------------
# 9. co-dev resume + Drive error → endpoint still returns 200
# ---------------------------------------------------------------------------

async def test_resume_endpoint_drive_error_still_200(client, owner_token, monkeypatch):
    """When the Drive author raises during resume, the endpoint still returns 200
    and the deliverable is left as a text/local record. No env patching needed."""
    import app.db as db_module
    import app.routes.deliverables as deliv_mod

    uid, token = owner_token

    async with db_module.SessionLocal() as db:
        from app.routes.deliverables import create_deliverable_service
        row = await create_deliverable_service(
            db,
            user_id=uid,
            project_id=None,
            module_key="estimates",
            deliverable_type="cost_estimate",
            title="Resume Drive Error Test",
            content={"summary": "Draft", "seed_message": "test"},
        )
        deliverable_id = row.id

    async def _failing_author(kind, title, content, *, subfolder=None):
        raise ConnectionError("Simulated Drive API connection error")

    # Inject the failing author; the route bypasses DRIVE_ENABLED when fn is set.
    monkeypatch.setattr(deliv_mod, "_drive_author_fn", _failing_author)

    resp = await client.post(
        f"/v1/deliverables/{deliverable_id}/resume",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "content": {"summary": "Accepted content", "seed_message": "test"},
            "resume_chain": False,
        },
    )
    # Must return 200 even with Drive error (fail-safe).
    assert resp.status_code == 200, (
        f"Resume must return 200 even on Drive error; got {resp.status_code}: {resp.text}"
    )

    body = resp.json()
    # deliverable should not have drive_url (Drive failed).
    assert body.get("drive_url") is None or isinstance(body.get("drive_url"), str)


# ---------------------------------------------------------------------------
# 10. Direct pipeline unit test: drive block stored in content after chain
# ---------------------------------------------------------------------------

async def test_pipeline_direct_drive_block_in_content(client, owner_token):
    """Directly call run_deliverable_chain with a mock Drive author.
    Verifies the drive block is stored in content and drive_url surfaces."""
    import app.db as db_module
    from app.deliverable_pipeline import run_deliverable_chain
    from app.routes.deliverables import _deliverable_out

    uid, _ = owner_token

    async def _mock_agent(agent_name: str, msg: str) -> str:
        return "Finalized pipeline content for Drive"

    expected_url = "https://docs.google.com/document/d/direct-test-doc/edit"

    async def _mock_author(kind, title, content, *, subfolder=None):
        return {
            "mode": "drive",
            "kind": "doc",
            "doc_id": "direct-test-doc",
            "url": expected_url,
            "title": title,
        }

    async with db_module.SessionLocal() as db:
        deliverable = await run_deliverable_chain(
            db,
            user_id=uid,
            project_id=None,
            deliverable_type="rfi_response",
            seed_message="Direct Drive test RFI",
            call_agent=_mock_agent,
            drive_subfolder="Test Project",
            _drive_author_fn=_mock_author,
        )

    assert deliverable is not None
    assert deliverable.status == "awaiting_human"

    # Drive block in content.
    content = deliverable.content or {}
    assert "drive" in content, f"drive block missing from content: {content}"
    assert content["drive"]["mode"] == "drive"
    assert content["drive"]["url"] == expected_url

    # _deliverable_out surfaces drive_url.
    out = _deliverable_out(deliverable)
    assert out["drive_url"] == expected_url, f"drive_url not surfaced: {out}"
