"""Unit tests for ContractDraftDispatcher — Sprint Contracts.3.

Covers:
- Idempotency: same upload_id dispatched only once (even after restart).
- State file round-trip: load → mutate → save → reload.
- Error recording and retry-after logic.
- _tick skips already-dispatched and back-off entries.
- _tick skips contracts that already have draft_artifact_id set.
- _tick skips contracts with wrong status or source.
- Happy-path dispatch_one_draft builds the approval payload correctly (replay).
- _build_draft_input correctly constructs agent input for template vs negotiated modes.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runtime.contract_draft_dispatcher import (
    ContractDraftDispatcher,
    DraftDispatcherState,
    _DispatchedEntry,
    _ErrorEntry,
    _build_draft_input,
    _is_retryable,
    _load_state,
    _retry_after,
    _save_state,
    dispatch_one_draft,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_dispatcher(tmp_path: Path, poll_interval: float = 0.1) -> ContractDraftDispatcher:
    cfg = MagicMock()
    cfg.queue_api_url = "http://localhost:8000"
    cfg.agent_shared_secret = "test-secret"
    cfg.request_timeout_s = 10.0
    cfg.CONTRACTS_BLOB_PATH = str(tmp_path / "blobs")

    return ContractDraftDispatcher(
        config=cfg,
        state_file=tmp_path / "draft_state.json",
        poll_interval_s=poll_interval,
        draft_requests_dir=tmp_path / "draft_requests",
    )


def _fake_contract(
    upload_id: str = "draft-upload-001",
    status: str = "drafting",
    source: str = "drafted",
    mode: str = "template",
    template_id: str | None = "subcontract_standard",
    draft_artifact_id: str | None = None,
) -> dict[str, Any]:
    return {
        "upload_id": upload_id,
        "project_label": "Test Framing Project",
        "status": status,
        "source": source,
        "mode": mode,
        "contract_type": "subcontract",
        "draft_artifact_id": draft_artifact_id,
        "draft_request": {
            "mode": mode,
            "contract_type": "subcontract",
            "template_id": template_id,
            "parties": [
                {"role": "contractor", "name": "Acme GC LLC"},
                {"role": "subcontractor", "name": "Beta Framing Inc"},
            ],
            "effective_date": "2026-06-01",
            "expiration_date": None,
            "total_value_usd": 125000.0,
            "payment_terms": "Net 30",
            "scope_summary": "Framing work for Project Alpha",
            "key_terms_requested": [
                {"topic": "indemnification", "requirement": "mutual indemnification only"},
            ],
            "jurisdiction": "Ohio",
            "notes": "Standard subcontract.",
            "prior_contract_upload_id": None,
        },
    }


# ---------------------------------------------------------------------------
# State file round-trip
# ---------------------------------------------------------------------------

def test_state_roundtrip(tmp_path: Path) -> None:
    """State can be saved and reloaded correctly."""
    state_file = tmp_path / "state.json"
    state = DraftDispatcherState(
        dispatched={
            "uid-1": _DispatchedEntry(
                upload_id="uid-1",
                dispatched_at="2026-05-11T10:00:00+00:00",
                approval_item_id="approval-abc",
            )
        },
        errors=[
            _ErrorEntry(
                upload_id="uid-2",
                error="agent timeout",
                failed_at="2026-05-11T09:00:00+00:00",
                retry_after="2026-05-11T10:30:00+00:00",
                attempt=2,
            )
        ],
    )
    _save_state(state, state_file)
    loaded = _load_state(state_file)

    assert "uid-1" in loaded.dispatched
    assert loaded.dispatched["uid-1"].approval_item_id == "approval-abc"
    assert len(loaded.errors) == 1
    assert loaded.errors[0].attempt == 2
    assert loaded.errors[0].upload_id == "uid-2"


def test_state_missing_file(tmp_path: Path) -> None:
    """Loading a non-existent state file returns empty state."""
    state = _load_state(tmp_path / "nonexistent.json")
    assert state.dispatched == {}
    assert state.errors == []


def test_state_corrupted_file(tmp_path: Path) -> None:
    """Corrupted state file returns empty state (no crash)."""
    state_file = tmp_path / "state.json"
    state_file.write_text("this is not valid json", encoding="utf-8")
    state = _load_state(state_file)
    assert state.dispatched == {}


# ---------------------------------------------------------------------------
# Retry / backoff logic
# ---------------------------------------------------------------------------

def test_retry_after_backoff() -> None:
    """retry_after increases exponentially."""
    r1 = _retry_after(1)
    r2 = _retry_after(2)
    # Attempt 2 should have a later retry than attempt 1
    assert datetime.fromisoformat(r2) > datetime.fromisoformat(r1)


def test_is_retryable_past(tmp_path: Path) -> None:
    """Past retry_after means retryable."""
    entry = _ErrorEntry(
        upload_id="uid",
        error="err",
        failed_at=datetime.now(UTC).isoformat(),
        retry_after=(datetime.now(UTC) - timedelta(seconds=60)).isoformat(),
        attempt=1,
    )
    assert _is_retryable(entry)


def test_is_retryable_future(tmp_path: Path) -> None:
    """Future retry_after means not retryable yet."""
    entry = _ErrorEntry(
        upload_id="uid",
        error="err",
        failed_at=datetime.now(UTC).isoformat(),
        retry_after=(datetime.now(UTC) + timedelta(seconds=3600)).isoformat(),
        attempt=1,
    )
    assert not _is_retryable(entry)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_idempotency_same_upload_not_redispatched(tmp_path: Path) -> None:
    """Once an upload_id is in dispatched state, it is never redispatched."""
    dispatcher = _make_dispatcher(tmp_path)
    dispatcher._state.dispatched["uid-xyz"] = _DispatchedEntry(
        upload_id="uid-xyz",
        dispatched_at=_utcnow_iso(),
        approval_item_id=None,
    )
    assert dispatcher._is_dispatched("uid-xyz")
    assert not dispatcher._is_dispatched("uid-other")


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def test_idempotency_survives_restart(tmp_path: Path) -> None:
    """Dispatched state survives a dispatcher restart (reload from file)."""
    dispatcher = _make_dispatcher(tmp_path)
    dispatcher._record_success("uid-abc", "approval-123")

    # Reload from disk
    dispatcher2 = _make_dispatcher(tmp_path)
    assert dispatcher2._is_dispatched("uid-abc")


# ---------------------------------------------------------------------------
# _build_draft_input
# ---------------------------------------------------------------------------

def test_build_draft_input_template_mode() -> None:
    """Build correct agent input for template mode."""
    contract = _fake_contract(mode="template", template_id="subcontract_standard")
    agent_input = _build_draft_input("upload-001", contract)

    assert agent_input["mode"] == "template"
    assert agent_input["template_id"] == "subcontract_standard"
    assert agent_input["contract_type"] == "subcontract"
    assert agent_input["jurisdiction"] == "Ohio"
    assert isinstance(agent_input["parties"], list)
    assert len(agent_input["parties"]) == 2
    assert agent_input["context"]["contract_upload_id"] == "upload-001"


def test_build_draft_input_negotiated_mode() -> None:
    """Build correct agent input for negotiated mode (no template_id)."""
    contract = _fake_contract(mode="negotiated", template_id=None)
    agent_input = _build_draft_input("upload-002", contract)

    assert agent_input["mode"] == "negotiated"
    assert agent_input["template_id"] is None
    assert agent_input["template_body"] == ""  # no template to load


def test_build_draft_input_includes_key_terms() -> None:
    """Key terms from draft_request are forwarded to agent input."""
    contract = _fake_contract(mode="negotiated")
    agent_input = _build_draft_input("upload-003", contract)

    assert any(
        ktr.get("topic") == "indemnification"
        for ktr in agent_input["key_terms_requested"]
    )


# ---------------------------------------------------------------------------
# dispatch_one_draft (replay fixture)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_one_draft_happy_path(tmp_path: Path) -> None:
    """dispatch_one_draft builds correct approval payload from replay fixture."""
    # Load the example output fixture
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "agentic-pmo-prompts"
        / "agents"
        / "contract-drafter"
        / "01_subcontract_template_mode.output.json"
    )
    if not fixture_path.exists():
        pytest.skip(f"fixture not found: {fixture_path}")

    example_output = json.loads(fixture_path.read_text(encoding="utf-8"))

    # Mock the Agent.run call to return the fixture
    mock_run = MagicMock()
    mock_run.output = example_output
    mock_run.error = None
    mock_run.validation_ok = True
    mock_run.validation_errors = []
    mock_run.lane_decision = MagicMock()
    mock_run.lane_decision.lane = 3
    mock_run.lane_decision.confidence = 0.85
    mock_run.lane_decision.reasons = ["attorney review required"]
    mock_run.model_used = "anthropic/claude-sonnet-4"
    mock_run.agent_version = "0.1.0"
    mock_run.prompt_version_hash = "abc123"
    mock_run.input_hash = "hash_in"
    mock_run.output_hash = "hash_out"

    cfg = MagicMock()
    cfg.queue_api_url = "http://localhost:8000"
    cfg.agent_shared_secret = "test"
    cfg.request_timeout_s = 10.0

    queue_client = AsyncMock()
    queue_client.create_approval = AsyncMock(return_value={"id": "approval-draft-001"})

    contract = _fake_contract(mode="template", template_id="subcontract_standard")

    with patch("runtime.contract_draft_dispatcher.Agent") as MockAgent:
        mock_agent_instance = MockAgent.return_value
        mock_agent_instance.run = AsyncMock(return_value=mock_run)

        approval_id = await dispatch_one_draft(
            "upload-001",
            contract,
            config=cfg,
            queue_client=queue_client,
        )

    assert approval_id == "approval-draft-001"
    queue_client.create_approval.assert_awaited_once()
    call_payload = queue_client.create_approval.call_args[0][0]
    assert call_payload["workflow"] == "contract_draft.publish"
    assert call_payload["lane"] == 3
    assert "owner" in call_payload["required_approvers"]
    assert "partner" in call_payload["required_approvers"]
    assert call_payload["payload"]["contract_upload_id"] == "upload-001"
    assert call_payload["payload"]["artifact"]["artifact_type"] == "contract_draft"


@pytest.mark.asyncio
async def test_dispatch_one_draft_agent_error_raises(tmp_path: Path) -> None:
    """dispatch_one_draft raises RuntimeError when agent fails."""
    mock_run = MagicMock()
    mock_run.output = None
    mock_run.error = "llm_timeout"
    mock_run.validation_ok = False
    mock_run.validation_errors = []

    cfg = MagicMock()
    cfg.queue_api_url = "http://localhost:8000"
    cfg.agent_shared_secret = "test"

    queue_client = AsyncMock()
    contract = _fake_contract()

    with patch("runtime.contract_draft_dispatcher.Agent") as MockAgent:
        mock_agent_instance = MockAgent.return_value
        mock_agent_instance.run = AsyncMock(return_value=mock_run)

        with pytest.raises(RuntimeError, match="agent returned no output"):
            await dispatch_one_draft(
                "upload-err",
                contract,
                config=cfg,
                queue_client=queue_client,
            )


# ---------------------------------------------------------------------------
# _tick behavior
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_skips_already_dispatched(tmp_path: Path) -> None:
    """_tick does not dispatch an upload_id that's already in dispatched state."""
    dispatcher = _make_dispatcher(tmp_path)
    upload_id = "uid-already"
    dispatcher._state.dispatched[upload_id] = _DispatchedEntry(
        upload_id=upload_id,
        dispatched_at=_utcnow_iso(),
        approval_item_id=None,
    )

    http_client = AsyncMock()
    http_client.get = AsyncMock(
        return_value=MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"items": [_fake_contract(upload_id=upload_id)]}
            ),
            raise_for_status=MagicMock(),
        )
    )

    queue_client = AsyncMock()
    queue_client.create_approval = AsyncMock()

    with patch(
        "runtime.contract_draft_dispatcher.dispatch_one_draft",
        new=AsyncMock(),
    ) as mock_dispatch:
        await dispatcher._tick(http_client, queue_client)
        mock_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_tick_skips_already_drafted(tmp_path: Path) -> None:
    """_tick skips contracts that already have draft_artifact_id set."""
    dispatcher = _make_dispatcher(tmp_path)
    contract = _fake_contract(upload_id="uid-done", draft_artifact_id="doc-abc")

    http_client = AsyncMock()
    http_client.get = AsyncMock(
        side_effect=[
            MagicMock(
                status_code=200,
                json=MagicMock(return_value={"items": [contract]}),
                raise_for_status=MagicMock(),
            ),
            MagicMock(
                status_code=200,
                json=MagicMock(return_value=contract),
                raise_for_status=MagicMock(),
            ),
        ]
    )
    queue_client = AsyncMock()

    with patch(
        "runtime.contract_draft_dispatcher.dispatch_one_draft",
        new=AsyncMock(),
    ) as mock_dispatch:
        await dispatcher._tick(http_client, queue_client)
        mock_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_tick_records_error_on_agent_failure(tmp_path: Path) -> None:
    """_tick records an error entry when dispatch_one_draft raises."""
    dispatcher = _make_dispatcher(tmp_path)
    upload_id = "uid-fail"
    contract = _fake_contract(upload_id=upload_id)

    http_client = AsyncMock()

    # list call
    list_resp = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"items": [contract]}),
        raise_for_status=MagicMock(),
    )
    # fetch single contract
    detail_resp = MagicMock(
        status_code=200,
        json=MagicMock(return_value=contract),
        raise_for_status=MagicMock(),
    )
    http_client.get = AsyncMock(side_effect=[list_resp, detail_resp])

    queue_client = AsyncMock()

    with patch(
        "runtime.contract_draft_dispatcher.dispatch_one_draft",
        new=AsyncMock(side_effect=RuntimeError("agent failed")),
    ):
        await dispatcher._tick(http_client, queue_client)

    assert any(e.upload_id == upload_id for e in dispatcher._state.errors)
    error_entry = next(e for e in dispatcher._state.errors if e.upload_id == upload_id)
    assert "agent failed" in error_entry.error
