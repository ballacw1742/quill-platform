"""Unit tests for ContractDispatcher — Sprint Contracts.1.

Covers:
- Idempotency: same upload_id dispatched only once (even after restart).
- State file round-trip: load → mutate → save → reload.
- Error recording and retry-after logic.
- _tick skips already-dispatched and back-off entries.
- Happy-path dispatch_one builds the approval payload correctly (replay mode).
- Backoff increments on repeated failure.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runtime.contract_dispatcher import (
    ContractDispatcher,
    DispatcherState,
    _DispatchedEntry,
    _ErrorEntry,
    _backoff_for,
    _is_retryable,
    _load_state,
    _retry_after,
    _save_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_dispatcher(tmp_path: Path, poll_interval: float = 0.1) -> ContractDispatcher:
    """Return a dispatcher with a mock config and a temp state file."""
    cfg = MagicMock()
    cfg.queue_api_url = "http://localhost:8000"
    cfg.agent_shared_secret = "test-secret"
    cfg.request_timeout_s = 10.0

    return ContractDispatcher(
        config=cfg,
        state_file=tmp_path / "state.json",
        poll_interval_s=poll_interval,
        dispatch_requests_dir=tmp_path / "dispatch_requests",
    )


def _fake_contract(upload_id: str = "upload-001") -> dict[str, Any]:
    return {
        "upload_id": upload_id,
        "project_label": "Test Project",
        "notes": "",
        "status": "extracted",
        "contract_type": "subcontract",
        "extracted_fields": None,
        "uploaded_files": [
            {
                "filename": "subcontract.pdf",
                "kind": "pdf",
                "size_bytes": 1000,
                "extraction_status": "ok",
                "extraction_summary": "Contract text extracted",
                "minio_key": f"contracts/{upload_id}/raw/subcontract.pdf",
            }
        ],
        "parties": [],
        "created_at": "2026-05-11T12:00:00+00:00",
        "updated_at": "2026-05-11T12:00:01+00:00",
        "disclaimer": "AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision.",
    }


# ---------------------------------------------------------------------------
# State file round-trip
# ---------------------------------------------------------------------------
def test_state_roundtrip(tmp_path: Path) -> None:
    sf = tmp_path / "state.json"
    state = DispatcherState()
    state.dispatched["upload-abc"] = _DispatchedEntry(
        upload_id="upload-abc",
        dispatched_at="2026-01-01T00:00:00+00:00",
        approval_item_id="appr-111",
    )
    state.errors.append(
        _ErrorEntry(
            upload_id="upload-xyz",
            error="agent failed",
            failed_at="2026-01-01T00:00:00+00:00",
            retry_after="2026-01-01T00:01:00+00:00",
            attempt=1,
        )
    )
    _save_state(state, sf)
    loaded = _load_state(sf)
    assert "upload-abc" in loaded.dispatched
    assert loaded.dispatched["upload-abc"].approval_item_id == "appr-111"
    assert len(loaded.errors) == 1
    assert loaded.errors[0].upload_id == "upload-xyz"
    assert loaded.errors[0].attempt == 1


def test_load_state_missing_file(tmp_path: Path) -> None:
    state = _load_state(tmp_path / "does_not_exist.json")
    assert state.dispatched == {}
    assert state.errors == []


def test_load_state_corrupt_file(tmp_path: Path) -> None:
    sf = tmp_path / "state.json"
    sf.write_text("NOT JSON", encoding="utf-8")
    state = _load_state(sf)
    assert state.dispatched == {}


def test_save_state_atomic(tmp_path: Path) -> None:
    sf = tmp_path / "state.json"
    state = DispatcherState()
    state.dispatched["u1"] = _DispatchedEntry("u1", "2026-01-01T00:00:00+00:00")
    _save_state(state, sf)
    assert sf.exists()
    tmp = sf.with_suffix(".json.tmp")
    assert not tmp.exists()  # atomically replaced


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------
def test_backoff_increases_exponentially() -> None:
    b1 = _backoff_for(1)
    b2 = _backoff_for(2)
    b3 = _backoff_for(3)
    assert b1 < b2 < b3


def test_backoff_capped_at_5min() -> None:
    from runtime.contract_dispatcher import _MAX_BACKOFF_S

    assert _backoff_for(100) == _MAX_BACKOFF_S


def test_is_retryable_past() -> None:
    past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    entry = _ErrorEntry("u", "err", past, past, 1)
    assert _is_retryable(entry)


def test_is_retryable_future() -> None:
    future = (datetime.now(UTC) + timedelta(seconds=600)).isoformat()
    entry = _ErrorEntry("u", "err", future, future, 1)
    assert not _is_retryable(entry)


# ---------------------------------------------------------------------------
# Dispatcher state management
# ---------------------------------------------------------------------------
def test_is_dispatched_after_record_success(tmp_path: Path) -> None:
    d = _make_dispatcher(tmp_path)
    assert not d._is_dispatched("upload-abc")
    d._record_success("upload-abc", "appr-001")
    assert d._is_dispatched("upload-abc")


def test_error_increments_attempt(tmp_path: Path) -> None:
    d = _make_dispatcher(tmp_path)
    d._record_error("upload-xyz", "timeout")
    assert d._get_error_entry("upload-xyz") is not None
    assert d._get_error_entry("upload-xyz").attempt == 1  # type: ignore[union-attr]
    d._record_error("upload-xyz", "timeout again")
    assert d._get_error_entry("upload-xyz").attempt == 2  # type: ignore[union-attr]


def test_success_clears_error(tmp_path: Path) -> None:
    d = _make_dispatcher(tmp_path)
    d._record_error("upload-abc", "boom")
    assert d._get_error_entry("upload-abc") is not None
    d._record_success("upload-abc", "appr-001")
    assert d._get_error_entry("upload-abc") is None
    assert d._is_dispatched("upload-abc")


# ---------------------------------------------------------------------------
# Tick skips already-dispatched items
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tick_skips_already_dispatched(tmp_path: Path) -> None:
    d = _make_dispatcher(tmp_path)
    upload_id = "upload-already"
    d._record_success(upload_id, "old-appr")

    contract = _fake_contract(upload_id)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        return_value=MagicMock(
            status_code=200,
            json=lambda: {"items": [{"upload_id": upload_id}]},
        )
    )
    mock_queue = AsyncMock()

    # dispatch_one should NOT be called for an already-dispatched item
    with patch("runtime.contract_dispatcher.dispatch_one", new=AsyncMock(return_value="appr-new")) as mock_dispatch:
        await d._tick(mock_client, mock_queue)
        mock_dispatch.assert_not_called()


# ---------------------------------------------------------------------------
# Tick skips backoff entries
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tick_skips_backoff_entry(tmp_path: Path) -> None:
    d = _make_dispatcher(tmp_path)
    upload_id = "upload-backoff"
    # Record an error with retry_after far in the future
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    d._state.errors.append(
        _ErrorEntry(upload_id, "boom", future, future, attempt=1)
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        return_value=MagicMock(
            status_code=200,
            json=lambda: {"items": [{"upload_id": upload_id}]},
        )
    )
    mock_queue = AsyncMock()

    with patch("runtime.contract_dispatcher.dispatch_one", new=AsyncMock(return_value="appr-x")) as mock_dispatch:
        await d._tick(mock_client, mock_queue)
        mock_dispatch.assert_not_called()


# ---------------------------------------------------------------------------
# Happy-path dispatch_one with replay fixture
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_one_happy_path(tmp_path: Path) -> None:
    """dispatch_one with a mocked agent (replay) should create an approval."""
    import json as _json
    from pathlib import Path as _Path

    # Load the example output fixture (01_subcontract.output.json)
    prompts_repo = _Path(__file__).resolve().parents[4] / "agentic-pmo-prompts"
    fixture_path = prompts_repo / "agents" / "contract-extractor" / "examples" / "01_subcontract.output.json"

    if not fixture_path.exists():
        pytest.skip(f"fixture not found: {fixture_path}")

    replay_output = _json.loads(fixture_path.read_text(encoding="utf-8"))

    # Write a fake extracted text blob
    blob_root = tmp_path / "blobs"
    blob_root.mkdir()
    extracted_path = blob_root / "contracts" / "upload-001" / "extracted"
    extracted_path.mkdir(parents=True)
    (extracted_path / "subcontract_pdf.txt").write_text(
        "SUBCONTRACT AGREEMENT\nThis Subcontract...", encoding="utf-8"
    )

    cfg = MagicMock()
    cfg.queue_api_url = "http://localhost:8000"
    cfg.agent_shared_secret = "test-secret"
    cfg.request_timeout_s = 10.0
    # Point prompts_repo_path so Agent can find the agent.md
    cfg.prompts_repo_path = prompts_repo

    contract_data = _fake_contract("upload-001")
    contract_data["uploaded_files"][0]["filename"] = "subcontract_pdf"

    # Build mock AgentRun result
    from unittest.mock import MagicMock

    mock_run = MagicMock()
    mock_run.output = replay_output
    mock_run.error = None
    mock_run.validation_ok = True
    mock_run.validation_errors = []
    mock_run.agent_version = "0.1.0"
    mock_run.model_used = "replay::contract-extractor"
    mock_run.prompt_version_hash = "abc123"
    mock_run.input_hash = "input-hash-abc"
    mock_run.output_hash = "output-hash-xyz"

    mock_lane = MagicMock()
    mock_lane.lane = 2
    mock_lane.confidence = 0.85
    mock_lane.reasons = ["tier-1-spotcheck"]
    mock_run.lane_decision = mock_lane

    mock_queue = AsyncMock()
    mock_queue.create_approval = AsyncMock(return_value={"id": "appr-test-001"})

    with patch("runtime.contract_dispatcher.Agent") as MockAgent:
        MockAgent.return_value.run = AsyncMock(return_value=mock_run)

        from runtime.contract_dispatcher import dispatch_one

        result = await dispatch_one(
            "upload-001",
            contract_data,
            config=cfg,
            queue_client=mock_queue,
            blob_root=blob_root,
        )

    assert result == "appr-test-001"
    mock_queue.create_approval.assert_called_once()
    call_payload = mock_queue.create_approval.call_args[0][0]
    assert call_payload["workflow"] == "contract_extraction.publish"
    assert call_payload["payload"]["contract_upload_id"] == "upload-001"
    assert call_payload["payload"]["context"]["contract_upload_id"] == "upload-001"


# ---------------------------------------------------------------------------
# Backoff on repeated failure in tick
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tick_records_error_on_dispatch_failure(tmp_path: Path) -> None:
    d = _make_dispatcher(tmp_path)
    upload_id = "upload-fail"

    contract = _fake_contract(upload_id)

    mock_client = AsyncMock()
    # First call: list extracted contracts
    mock_client.get = AsyncMock(
        side_effect=[
            MagicMock(
                status_code=200,
                json=lambda: {"items": [{"upload_id": upload_id}]},
                raise_for_status=lambda: None,
            ),
            MagicMock(
                status_code=200,
                json=lambda: contract,
                raise_for_status=lambda: None,
            ),
        ]
    )

    mock_queue = AsyncMock()

    with patch(
        "runtime.contract_dispatcher.dispatch_one",
        new=AsyncMock(side_effect=RuntimeError("agent exploded")),
    ):
        await d._tick(mock_client, mock_queue)

    err = d._get_error_entry(upload_id)
    assert err is not None
    assert err.attempt == 1
    assert "agent exploded" in err.error


# ---------------------------------------------------------------------------
# Priority marker detection
# ---------------------------------------------------------------------------
def test_priority_upload_ids(tmp_path: Path) -> None:
    d = _make_dispatcher(tmp_path)
    requests_dir = tmp_path / "dispatch_requests"
    requests_dir.mkdir()
    (requests_dir / "upload-priority.json").write_text(
        json.dumps({"upload_id": "upload-priority"}), encoding="utf-8"
    )
    ids = d._priority_upload_ids()
    assert "upload-priority" in ids


def test_get_status_dict(tmp_path: Path) -> None:
    d = _make_dispatcher(tmp_path)
    d._record_success("upload-1", "appr-1")
    d._record_error("upload-2", "boom")
    status = d.get_status_dict()
    assert status["dispatched_count"] == 1
    assert status["error_count"] == 1
    assert any(e["upload_id"] == "upload-1" for e in status["recent_dispatched"])
