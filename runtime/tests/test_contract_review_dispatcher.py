"""Unit tests for ContractReviewDispatcher — Sprint Contracts.2.

Covers:
- Idempotency: same upload_id reviewed only once (even after restart).
- State file round-trip: load → mutate → save → reload.
- Error recording and retry-after logic.
- _tick skips already-dispatched and back-off entries.
- _tick skips contracts that already have review_artifact_id set.
- _tick skips contracts with no extracted_fields.
- Happy-path dispatch_one_review builds the approval payload correctly (replay).
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runtime.contract_review_dispatcher import (
    ContractReviewDispatcher,
    ReviewDispatcherState,
    _DispatchedEntry,
    _ErrorEntry,
    _is_retryable,
    _load_state,
    _retry_after,
    _save_state,
    dispatch_one_review,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_dispatcher(tmp_path: Path, poll_interval: float = 0.1) -> ContractReviewDispatcher:
    cfg = MagicMock()
    cfg.queue_api_url = "http://localhost:8000"
    cfg.agent_shared_secret = "test-secret"
    cfg.request_timeout_s = 10.0
    # Avoid real blob path issues in tests
    cfg.CONTRACTS_BLOB_PATH = str(tmp_path / "blobs")

    return ContractReviewDispatcher(
        config=cfg,
        state_file=tmp_path / "review_state.json",
        poll_interval_s=poll_interval,
        review_requests_dir=tmp_path / "review_requests",
    )


def _fake_contract(
    upload_id: str = "review-upload-001",
    with_extracted: bool = True,
    review_artifact_id: str | None = None,
) -> dict[str, Any]:
    c: dict[str, Any] = {
        "upload_id": upload_id,
        "project_label": "Test Project",
        "status": "extracted",
        "contract_type": "subcontract",
        "uploaded_files": [
            {
                "filename": "contract.txt",
                "kind": "other",
                "extraction_status": "ok",
                "extraction_summary": "Subcontractor shall indemnify Contractor.",
                "extracted_text_key": None,
            }
        ],
    }
    if with_extracted:
        c["extracted_fields"] = {
            "artifact_type": "contract_extraction",
            "contract_type": "subcontract",
            "parties": [],
            "disclaimer": "AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision.",
        }
    else:
        c["extracted_fields"] = None
    c["review_artifact_id"] = review_artifact_id
    return c


_MOCK_REVIEW_OUTPUT = {
    "risk_flags": [
        {
            "severity": "high",
            "category": "indemnification",
            "title": "One-sided indemnity",
            "summary": "Indemnity is one-sided.",
            "verbatim": "Subcontractor shall indemnify Contractor.",
            "location": "Section 14",
            "why_it_matters": "You bear all risk.",
            "suggested_action": "Negotiate mutual indemnity.",
        }
    ],
    "missing_protections": [],
    "market_terms_assessment": {
        "payment_terms": {"verdict": "unclear", "notes": "Not assessed."},
        "retention": {"verdict": "unclear", "notes": "Not assessed."},
        "indemnification": {"verdict": "off-market-unfavorable", "notes": "One-sided."},
        "limitation_of_liability": {"verdict": "not-present", "notes": "No cap."},
        "termination": {"verdict": "unclear", "notes": "Not assessed."},
        "change_orders": {"verdict": "unclear", "notes": "Not assessed."},
        "dispute_resolution": {"verdict": "unclear", "notes": "Not assessed."},
        "insurance": {"verdict": "unclear", "notes": "Not assessed."},
    },
    "plain_english_summary": "This is a subcontract with one-sided indemnity.",
    "recommended_actions": ["Confirm with counsel."],
    "disclaimer": "AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision.",
    "citations": [{"quote": "Subcontractor shall indemnify.", "location": "Section 14"}],
}


# ---------------------------------------------------------------------------
# State round-trip
# ---------------------------------------------------------------------------
def test_state_round_trip(tmp_path: Path) -> None:
    state = ReviewDispatcherState(
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
                error="timeout",
                failed_at="2026-05-11T09:00:00+00:00",
                retry_after="2026-05-11T09:30:00+00:00",
                attempt=1,
            )
        ],
    )
    state_file = tmp_path / "state.json"
    _save_state(state, state_file)
    loaded = _load_state(state_file)
    assert "uid-1" in loaded.dispatched
    assert loaded.dispatched["uid-1"].approval_item_id == "approval-abc"
    assert len(loaded.errors) == 1
    assert loaded.errors[0].upload_id == "uid-2"


def test_load_state_missing_file(tmp_path: Path) -> None:
    state = _load_state(tmp_path / "nonexistent.json")
    assert state.dispatched == {}
    assert state.errors == []


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_idempotency_same_upload_id(tmp_path: Path) -> None:
    """Once dispatched, the same upload_id is never dispatched again."""
    dispatcher = _make_dispatcher(tmp_path)
    dispatcher._record_success("uid-1", "approval-1")
    assert dispatcher._is_dispatched("uid-1")

    # Simulate a "restart" by loading state fresh
    dispatcher2 = _make_dispatcher(tmp_path)
    assert dispatcher2._is_dispatched("uid-1")


# ---------------------------------------------------------------------------
# Error recording and backoff
# ---------------------------------------------------------------------------
def test_error_recording(tmp_path: Path) -> None:
    dispatcher = _make_dispatcher(tmp_path)
    dispatcher._record_error("uid-err", "connection timeout")
    entry = dispatcher._get_error_entry("uid-err")
    assert entry is not None
    assert entry.attempt == 1
    assert entry.error == "connection timeout"

    # Record again — attempt should increment
    dispatcher._record_error("uid-err", "connection timeout again")
    entry2 = dispatcher._get_error_entry("uid-err")
    assert entry2 is not None
    assert entry2.attempt == 2


def test_is_retryable_past_retry_after() -> None:
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    entry = _ErrorEntry(
        upload_id="uid",
        error="err",
        failed_at=past,
        retry_after=past,
        attempt=1,
    )
    assert _is_retryable(entry) is True


def test_is_retryable_future_retry_after() -> None:
    future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    entry = _ErrorEntry(
        upload_id="uid",
        error="err",
        failed_at=future,
        retry_after=future,
        attempt=1,
    )
    assert _is_retryable(entry) is False


# ---------------------------------------------------------------------------
# _tick skips
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tick_skips_already_dispatched(tmp_path: Path) -> None:
    dispatcher = _make_dispatcher(tmp_path)
    dispatcher._record_success("uid-dispatched", "approval-xyz")

    contracts = [_fake_contract("uid-dispatched")]

    async def _fetch_extracted(*args, **kwargs):
        return contracts

    async def _fetch_contract(*args, **kwargs):
        return None  # should not be called

    with patch(
        "runtime.contract_review_dispatcher._fetch_extracted_contracts",
        new=AsyncMock(side_effect=_fetch_extracted),
    ), patch(
        "runtime.contract_review_dispatcher._fetch_contract",
        new=AsyncMock(side_effect=_fetch_contract),
    ):
        await dispatcher._tick(MagicMock(), MagicMock())

    # No new records added
    assert len(dispatcher._state.dispatched) == 1


@pytest.mark.asyncio
async def test_tick_skips_already_reviewed(tmp_path: Path) -> None:
    """Skip contracts that already have review_artifact_id set (race condition)."""
    dispatcher = _make_dispatcher(tmp_path)
    contracts = [_fake_contract("uid-reviewed")]

    async def _fetch_extracted(*args, **kwargs):
        return contracts

    async def _fetch_contract(*args, **kwargs):
        return _fake_contract("uid-reviewed", review_artifact_id="existing-review-123")

    with patch(
        "runtime.contract_review_dispatcher._fetch_extracted_contracts",
        new=AsyncMock(side_effect=_fetch_extracted),
    ), patch(
        "runtime.contract_review_dispatcher._fetch_contract",
        new=AsyncMock(side_effect=_fetch_contract),
    ):
        await dispatcher._tick(MagicMock(), MagicMock())

    # Should be recorded as success (already reviewed)
    assert dispatcher._is_dispatched("uid-reviewed")


@pytest.mark.asyncio
async def test_tick_skips_no_extracted_fields(tmp_path: Path) -> None:
    """Skip contracts with no extracted_fields."""
    dispatcher = _make_dispatcher(tmp_path)
    contracts = [_fake_contract("uid-no-extract", with_extracted=False)]

    async def _fetch_extracted(*args, **kwargs):
        return contracts

    async def _fetch_contract(*args, **kwargs):
        return _fake_contract("uid-no-extract", with_extracted=False)

    with patch(
        "runtime.contract_review_dispatcher._fetch_extracted_contracts",
        new=AsyncMock(side_effect=_fetch_extracted),
    ), patch(
        "runtime.contract_review_dispatcher._fetch_contract",
        new=AsyncMock(side_effect=_fetch_contract),
    ):
        await dispatcher._tick(MagicMock(), MagicMock())

    # Not dispatched (skipped due to no extracted_fields)
    assert not dispatcher._is_dispatched("uid-no-extract")


# ---------------------------------------------------------------------------
# Happy path with replay fixture
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_one_review_replay(tmp_path: Path) -> None:
    """dispatch_one_review builds approval payload correctly using a replay stub."""
    cfg = MagicMock()
    cfg.prompts_repo_path = Path("/Users/charlesmitchell/.openclaw/workspace/agentic-pmo-prompts")

    mock_run = MagicMock()
    mock_run.output = _MOCK_REVIEW_OUTPUT.copy()
    mock_run.error = None
    mock_run.validation_ok = True
    mock_run.validation_errors = []
    mock_run.model_used = "claude-sonnet-4-6"
    mock_run.agent_version = "0.1.0"
    mock_run.lane_decision = MagicMock(lane=2, confidence=0.85, reasons=["standard review"])
    mock_run.prompt_version_hash = "abc123"
    mock_run.input_hash = "input-hash-abc"
    mock_run.output_hash = "output-hash-def"

    mock_queue = AsyncMock()
    mock_queue.create_approval = AsyncMock(return_value={"id": "approval-review-001"})

    contract_data = _fake_contract("replay-upload-001")

    with patch("runtime.agent.Agent.run", new=AsyncMock(return_value=mock_run)):
        result = await dispatch_one_review(
            "replay-upload-001",
            contract_data,
            config=cfg,
            queue_client=mock_queue,
            blob_root=tmp_path / "blobs",
        )

    assert result == "approval-review-001"
    call_kwargs = mock_queue.create_approval.call_args[0][0]
    assert call_kwargs["agent_id"] == "contract-reviewer"
    assert call_kwargs["workflow"] == "contract_review.publish"
    assert call_kwargs["payload"]["contract_upload_id"] == "replay-upload-001"
    assert call_kwargs["payload"]["context"]["contract_upload_id"] == "replay-upload-001"
    # Disclaimer in artifact output
    assert call_kwargs["payload"]["artifact"]["disclaimer"].startswith("AI-generated")
