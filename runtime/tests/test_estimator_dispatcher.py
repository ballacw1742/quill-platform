"""Tests for EstimatorDispatcher — Phase G.6.

Coverage targets:
- Idempotency: same upload_id is never dispatched twice.
- Happy path: estimating estimate → approval item created.
- Skip when package_artifact_id is already set.
- Exponential back-off on repeated failures.
- State file persist + reload.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup: ensure runtime/ is importable without an editable install.
# ---------------------------------------------------------------------------
_RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(_RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_DIR))

# Stub heavy deps ONLY when they aren't installed in the test env.
# (Sprint 5.5 fix: unconditionally replacing sys.modules["httpx"] poisoned
# every test module imported after this one — test_queue_client's
# httpx.MockTransport went missing in full-suite runs.)
import importlib.util  # noqa: E402
import types as _types  # noqa: E402


def _stub_if_missing(name: str, **attrs: Any) -> None:
    if name in sys.modules or importlib.util.find_spec(name) is not None:
        return
    mod = _types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


_stub_if_missing("anthropic")
_stub_if_missing("structlog", get_logger=lambda *a, **kw: MagicMock())
_stub_if_missing("httpx", AsyncClient=MagicMock)


# ---------------------------------------------------------------------------
# Minimal Config + QueueClient stubs so we don't need the full env
# ---------------------------------------------------------------------------
class _StubConfig:
    queue_api_url = "http://localhost:8000"
    agent_shared_secret = "test-secret"
    request_timeout_s = 30
    prompts_repo_path = Path("/tmp/prompts")

    @property
    def anthropic_api_key(self) -> str:
        return "sk-test"


class _StubQueueClient:
    """Async context manager that records create_approval calls."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self._next_id = 0

    async def __aenter__(self) -> "_StubQueueClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass

    async def create_approval(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        item_id = f"approval-{self._next_id}"
        self.created.append({**payload, "id": item_id})
        return {"id": item_id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_estimate_status(
    upload_id: str,
    *,
    status: str = "estimating",
    classification_artifact_id: str | None = "cls-artifact-123",
    package_artifact_id: str | None = None,
) -> dict[str, Any]:
    return {
        "upload_id": upload_id,
        "status": status,
        "project_label": "Test Project",
        "notes": "",
        "uploaded_files": [
            {
                "filename": "plan.pdf",
                "kind": "pdf",
                "size_bytes": 1024,
                "extraction_status": "ok",
            }
        ],
        "classification_artifact_id": classification_artifact_id,
        "package_artifact_id": package_artifact_id,
    }


def _make_extraction_blob() -> dict[str, Any]:
    return {
        "filename": "plan.pdf",
        "kind": "pdf",
        "extraction_status": "ok",
        "summary": "A concept plan.",
        "entities": {"page_count": 3, "text_excerpts": []},
        "quantities": {},
        "renders": [],
        "errors": [],
        "size_bytes": 1024,
    }


def _make_classification_artifact() -> dict[str, Any]:
    return {
        "artifact_id": "cls-artifact-123",
        "artifact_type": "aace_classification",
        "confidence": 0.8,
        "metadata": {
            "class": "5",
            "design_maturity_estimate_pct": 1.5,
            "uploaded_files": [],
            "supporting_evidence": [],
            "design_disciplines_detected": ["program"],
            "missing_for_next_class": [],
        },
    }


def _make_agent_run(output: dict[str, Any] | None = None) -> MagicMock:
    run = MagicMock()
    run.output = output or {
        "artifact_id": "pkg-artifact-001",
        "artifact_type": "cost_schedule_package",
        "confidence": 0.7,
        "metadata": {
            "estimate": {"total_usd": 1_000_000, "rows": []},
            "schedule": {"total_duration_days": 365, "activities": []},
        },
    }
    run.error = None
    run.validation_ok = True
    run.validation_errors = []
    run.lane_decision = MagicMock(lane=2, confidence=0.7, reasons=["tier-2"])
    run.agent_version = "0.1.0"
    run.model_used = "claude-test"
    run.prompt_version_hash = "abc123" * 5
    run.input_hash = "input-hash"
    run.output_hash = "output-hash"
    return run


# ---------------------------------------------------------------------------
# Import the module under test AFTER stubs are in place
# ---------------------------------------------------------------------------
from runtime.estimator_dispatcher import (  # noqa: E402
    DispatcherState,
    EstimatorDispatcher,
    _backoff_for,
    _is_retryable,
    _load_state,
    _save_state,
    _ErrorEntry,
    _DispatchedEntry,
)


# ---------------------------------------------------------------------------
# State persistence tests
# ---------------------------------------------------------------------------
class TestStatePersistence:
    def test_roundtrip_empty(self, tmp_path: Path) -> None:
        sf = tmp_path / "state.json"
        state = DispatcherState()
        _save_state(state, sf)
        loaded = _load_state(sf)
        assert loaded.dispatched == {}
        assert loaded.errors == []

    def test_roundtrip_with_entries(self, tmp_path: Path) -> None:
        sf = tmp_path / "state.json"
        state = DispatcherState()
        state.dispatched["uid-1"] = _DispatchedEntry(
            upload_id="uid-1",
            dispatched_at="2026-01-01T00:00:00+00:00",
            approval_item_id="appr-1",
        )
        state.errors.append(
            _ErrorEntry(
                upload_id="uid-2",
                error="boom",
                failed_at="2026-01-01T01:00:00+00:00",
                retry_after="2026-01-01T02:00:00+00:00",
                attempt=2,
            )
        )
        _save_state(state, sf)
        loaded = _load_state(sf)
        assert "uid-1" in loaded.dispatched
        assert loaded.dispatched["uid-1"].approval_item_id == "appr-1"
        assert len(loaded.errors) == 1
        assert loaded.errors[0].attempt == 2

    def test_load_missing_file(self, tmp_path: Path) -> None:
        sf = tmp_path / "nonexistent.json"
        state = _load_state(sf)
        assert state.dispatched == {}
        assert state.errors == []

    def test_load_corrupt_file(self, tmp_path: Path) -> None:
        sf = tmp_path / "corrupt.json"
        sf.write_text("{not valid json}", encoding="utf-8")
        state = _load_state(sf)
        assert state.dispatched == {}


# ---------------------------------------------------------------------------
# Back-off tests
# ---------------------------------------------------------------------------
class TestBackoff:
    def test_backoff_grows(self) -> None:
        b1 = _backoff_for(1)
        b2 = _backoff_for(2)
        b3 = _backoff_for(3)
        assert b1 < b2 < b3

    def test_backoff_capped(self) -> None:
        assert _backoff_for(100) == 5 * 60  # capped at 5 min

    def test_is_retryable_past(self) -> None:
        e = _ErrorEntry(
            upload_id="x",
            error="boom",
            failed_at="2020-01-01T00:00:00+00:00",
            retry_after="2020-01-01T00:01:00+00:00",
            attempt=1,
        )
        assert _is_retryable(e) is True

    def test_is_retryable_future(self) -> None:
        e = _ErrorEntry(
            upload_id="x",
            error="boom",
            failed_at="2099-01-01T00:00:00+00:00",
            retry_after="2099-01-01T00:01:00+00:00",
            attempt=1,
        )
        assert _is_retryable(e) is False


# ---------------------------------------------------------------------------
# Idempotency tests
# ---------------------------------------------------------------------------
class TestIdempotency:
    def test_already_dispatched_is_skipped(self, tmp_path: Path) -> None:
        """If upload_id is in state, _is_dispatched returns True."""
        sf = tmp_path / "state.json"
        dispatcher = EstimatorDispatcher(
            config=_StubConfig(),
            state_file=sf,
        )
        uid = "some-upload-id"
        dispatcher._state.dispatched[uid] = _DispatchedEntry(
            upload_id=uid,
            dispatched_at="2026-01-01T00:00:00+00:00",
            approval_item_id="appr-x",
        )
        assert dispatcher._is_dispatched(uid) is True

    def test_record_success_prevents_requeue(self, tmp_path: Path) -> None:
        sf = tmp_path / "state.json"
        dispatcher = EstimatorDispatcher(config=_StubConfig(), state_file=sf)
        uid = "upload-abc"
        assert not dispatcher._is_dispatched(uid)
        dispatcher._record_success(uid, "appr-1")
        # Re-load from disk and verify.
        d2 = EstimatorDispatcher(config=_StubConfig(), state_file=sf)
        assert d2._is_dispatched(uid)

    def test_error_then_success_clears_error(self, tmp_path: Path) -> None:
        sf = tmp_path / "state.json"
        dispatcher = EstimatorDispatcher(config=_StubConfig(), state_file=sf)
        uid = "upload-xyz"
        dispatcher._record_error(uid, "timeout")
        assert dispatcher._get_error_entry(uid) is not None
        dispatcher._record_success(uid, "appr-2")
        assert dispatcher._get_error_entry(uid) is None
        assert dispatcher._is_dispatched(uid)


# ---------------------------------------------------------------------------
# Happy-path dispatch (mocked queue + agent)
# ---------------------------------------------------------------------------
class TestDispatchOneTick:
    """Exercise _tick via full EstimatorDispatcher._tick mock."""

    @pytest.mark.asyncio
    async def test_happy_path_dispatch(self, tmp_path: Path) -> None:
        """A fresh 'estimating' estimate with extraction blobs → approval item created."""
        upload_id = "upload-happy"
        sf = tmp_path / "state.json"
        blob_root = tmp_path / "blobs"
        # Write extraction blob
        blob_dir = blob_root / f"estimates/{upload_id}/extracted"
        blob_dir.mkdir(parents=True)
        (blob_dir / "plan.pdf.json").write_text(
            json.dumps(_make_extraction_blob()), encoding="utf-8"
        )

        config = _StubConfig()
        queue_client = _StubQueueClient()
        dispatcher = EstimatorDispatcher(
            config=config,
            state_file=sf,
            poll_interval_s=0.1,
        )
        dispatcher._blob_root = blob_root

        fake_agent_run = _make_agent_run()

        # Patch the API calls and the agent.
        with (
            patch(
                "runtime.estimator_dispatcher._fetch_estimating_estimates",
                new=AsyncMock(
                    return_value=[_make_estimate_status(upload_id)]
                ),
            ),
            patch(
                "runtime.estimator_dispatcher._fetch_estimate_status",
                new=AsyncMock(return_value=_make_estimate_status(upload_id)),
            ),
            patch(
                "runtime.estimator_dispatcher._fetch_classification_artifact",
                new=AsyncMock(return_value=_make_classification_artifact()),
            ),
            patch("runtime.estimator_dispatcher.Agent") as MockAgent,
        ):
            mock_agent_instance = AsyncMock()
            mock_agent_instance.run = AsyncMock(return_value=fake_agent_run)
            MockAgent.return_value = mock_agent_instance

            # Patch queue_client inside QueueClient context manager.
            with patch(
                "runtime.estimator_dispatcher.QueueClient",
                return_value=queue_client,
            ):
                import httpx as _httpx

                async with _httpx.AsyncClient() as http_client:
                    await dispatcher._tick(http_client, queue_client)

        assert dispatcher._is_dispatched(upload_id)
        assert len(queue_client.created) == 1
        approval = queue_client.created[0]
        assert approval["workflow"] == "cost_schedule_package.publish"
        assert approval["agent_id"] == "estimator-scheduler"
        payload = approval["payload"]
        assert payload["estimate_upload_id"] == upload_id
        assert payload["context"]["estimate_upload_id"] == upload_id

    @pytest.mark.asyncio
    async def test_skip_when_package_artifact_set(self, tmp_path: Path) -> None:
        """If package_artifact_id is already set, skip without dispatching."""
        upload_id = "upload-done"
        sf = tmp_path / "state.json"

        dispatcher = EstimatorDispatcher(config=_StubConfig(), state_file=sf)

        with (
            patch(
                "runtime.estimator_dispatcher._fetch_estimating_estimates",
                new=AsyncMock(
                    return_value=[_make_estimate_status(upload_id)]
                ),
            ),
            patch(
                "runtime.estimator_dispatcher._fetch_estimate_status",
                new=AsyncMock(
                    return_value=_make_estimate_status(
                        upload_id,
                        package_artifact_id="already-done",
                    )
                ),
            ),
        ):
            import httpx as _httpx

            queue_client = _StubQueueClient()
            async with _httpx.AsyncClient() as http_client:
                await dispatcher._tick(http_client, queue_client)

        # No approval created, but upload recorded as done.
        assert len(queue_client.created) == 0
        assert dispatcher._is_dispatched(upload_id)

    @pytest.mark.asyncio
    async def test_idempotent_on_restart(self, tmp_path: Path) -> None:
        """Loading an existing state file must not re-dispatch already-done uploads."""
        upload_id = "upload-already"
        sf = tmp_path / "state.json"

        # Pre-populate state as if previous run dispatched this.
        state = DispatcherState()
        state.dispatched[upload_id] = _DispatchedEntry(
            upload_id=upload_id,
            dispatched_at="2026-01-01T00:00:00+00:00",
            approval_item_id="appr-prev",
        )
        _save_state(state, sf)

        dispatcher = EstimatorDispatcher(config=_StubConfig(), state_file=sf)

        with (
            patch(
                "runtime.estimator_dispatcher._fetch_estimating_estimates",
                new=AsyncMock(
                    return_value=[_make_estimate_status(upload_id)]
                ),
            ),
        ):
            import httpx as _httpx

            queue_client = _StubQueueClient()
            async with _httpx.AsyncClient() as http_client:
                await dispatcher._tick(http_client, queue_client)

        assert len(queue_client.created) == 0

    @pytest.mark.asyncio
    async def test_error_recorded_on_agent_failure(self, tmp_path: Path) -> None:
        """If the agent raises, the error is recorded and no approval item created."""
        upload_id = "upload-fail"
        sf = tmp_path / "state.json"
        blob_root = tmp_path / "blobs"
        blob_dir = blob_root / f"estimates/{upload_id}/extracted"
        blob_dir.mkdir(parents=True)
        (blob_dir / "plan.pdf.json").write_text(
            json.dumps(_make_extraction_blob()), encoding="utf-8"
        )

        dispatcher = EstimatorDispatcher(config=_StubConfig(), state_file=sf)
        dispatcher._blob_root = blob_root

        with (
            patch(
                "runtime.estimator_dispatcher._fetch_estimating_estimates",
                new=AsyncMock(
                    return_value=[_make_estimate_status(upload_id)]
                ),
            ),
            patch(
                "runtime.estimator_dispatcher._fetch_estimate_status",
                new=AsyncMock(return_value=_make_estimate_status(upload_id)),
            ),
            patch(
                "runtime.estimator_dispatcher._fetch_classification_artifact",
                new=AsyncMock(return_value=_make_classification_artifact()),
            ),
            patch("runtime.estimator_dispatcher.Agent") as MockAgent,
        ):
            mock_agent_instance = AsyncMock()
            mock_agent_instance.run = AsyncMock(
                side_effect=RuntimeError("llm_error: model overload")
            )
            MockAgent.return_value = mock_agent_instance

            import httpx as _httpx

            queue_client = _StubQueueClient()
            async with _httpx.AsyncClient() as http_client:
                await dispatcher._tick(http_client, queue_client)

        assert len(queue_client.created) == 0
        assert not dispatcher._is_dispatched(upload_id)
        err = dispatcher._get_error_entry(upload_id)
        assert err is not None
        assert "llm_error" in err.error
        assert err.attempt == 1
