"""EstimatorDispatcher — Phase G.6.

Polling daemon that picks up estimate uploads in ``status='estimating'`` and
runs the ``estimator-scheduler`` agent on them, producing a
``cost_schedule_package`` approval item linked to the estimate via
``payload.estimate_upload_id``.

Design goals (mirrors ClassificationDispatcher from G.5):
- **Polling-resilient.** State file persists dispatched upload_ids across
  restarts.
- **Idempotent.** Same upload_id is only dispatched once; if
  ``package_artifact_id`` is already set on the estimate, it is skipped.
- **Crash-safe.** State file is written atomically (tmp→rename).
- **Graceful shutdown.** Handles SIGTERM / SIGINT without data loss.
- **Configurable poll interval.** ``ESTIMATE_POLL_INTERVAL_SECONDS`` env var.

State file location:
    ``runtime/_state/estimator_dispatched.json``

State schema::

    {
        "dispatched": {
            "<upload_id>": {
                "dispatched_at": "<iso>",
                "approval_item_id": "<id>"
            }
        },
        "errors": [
            {
                "upload_id": "<upload_id>",
                "error": "<message>",
                "failed_at": "<iso>",
                "retry_after": "<iso>",
                "attempt": <int>
            }
        ]
    }
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog

from runtime.agent import Agent, AgentRun
from runtime.config import Config, get_config
from runtime.queue_client import QueueClient

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_POLL_INTERVAL_S = 10.0
_DEFAULT_STATE_FILE_PATH = (
    Path(__file__).resolve().parents[2] / "_state" / "estimator_dispatched.json"
)
_DEFAULT_DISPATCH_REQUESTS_DIR = (
    Path(__file__).resolve().parents[2] / "_state" / "estimator_dispatch_requests"
)

# Maximum back-off on repeated failures for a single upload_id.
_MAX_BACKOFF_S = 5 * 60  # 5 minutes
_INITIAL_BACKOFF_S = 30.0


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------
@dataclass
class _DispatchedEntry:
    upload_id: str
    dispatched_at: str
    approval_item_id: str | None = None


@dataclass
class _ErrorEntry:
    upload_id: str
    error: str
    failed_at: str
    retry_after: str
    attempt: int = 1


@dataclass
class DispatcherState:
    dispatched: dict[str, _DispatchedEntry] = field(default_factory=dict)
    errors: list[_ErrorEntry] = field(default_factory=list)


def _load_state(state_file: Path) -> DispatcherState:
    if not state_file.exists():
        return DispatcherState()
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        dispatched = {}
        for uid, v in (raw.get("dispatched") or {}).items():
            dispatched[uid] = _DispatchedEntry(
                upload_id=uid,
                dispatched_at=v.get("dispatched_at", ""),
                approval_item_id=v.get("approval_item_id"),
            )
        errors = [
            _ErrorEntry(
                upload_id=e["upload_id"],
                error=e.get("error", ""),
                failed_at=e.get("failed_at", ""),
                retry_after=e.get("retry_after", ""),
                attempt=int(e.get("attempt", 1)),
            )
            for e in (raw.get("errors") or [])
        ]
        return DispatcherState(dispatched=dispatched, errors=errors)
    except Exception as exc:  # noqa: BLE001
        log.warning("estimate.state_load_failed", err=str(exc))
        return DispatcherState()


def _save_state(state: DispatcherState, state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dispatched": {
            uid: {
                "dispatched_at": e.dispatched_at,
                "approval_item_id": e.approval_item_id,
            }
            for uid, e in state.dispatched.items()
        },
        "errors": [
            {
                "upload_id": e.upload_id,
                "error": e.error,
                "failed_at": e.failed_at,
                "retry_after": e.retry_after,
                "attempt": e.attempt,
            }
            for e in state.errors
        ],
    }
    tmp = state_file.with_suffix(state_file.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, state_file)


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _backoff_for(attempt: int) -> float:
    """Exponential back-off, capped at _MAX_BACKOFF_S."""
    return min(_INITIAL_BACKOFF_S * (2 ** (attempt - 1)), _MAX_BACKOFF_S)


def _retry_after(attempt: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=_backoff_for(attempt))).isoformat()


def _is_retryable(error_entry: _ErrorEntry) -> bool:
    """True if the retry_after timestamp has passed."""
    try:
        ra = datetime.fromisoformat(error_entry.retry_after)
        return datetime.now(UTC) >= ra
    except Exception:  # noqa: BLE001
        return True


# ---------------------------------------------------------------------------
# Blob reading (mirrors classification_dispatcher.py)
# ---------------------------------------------------------------------------
def _blob_root(config: Config) -> Path:
    raw = os.environ.get("ESTIMATES_BLOB_PATH", "./_local_estimates")
    return Path(raw).resolve()


def _load_extracted_blob(
    upload_id: str, filename: str, blob_root: Path
) -> dict[str, Any] | None:
    """Load a per-file extraction JSON artifact from blob storage."""
    safe_name = filename.replace("/", "_").replace("\\", "_")
    key = f"estimates/{upload_id}/extracted/{safe_name}.json"
    target = (blob_root / key).resolve()
    if not str(target).startswith(str(blob_root)):
        log.warning("estimate.blob_path_escape", key=key)
        return None
    if not target.exists():
        log.warning("estimate.extracted_blob_not_found", path=str(target))
        return None
    try:
        raw = target.read_bytes()
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("estimate.blob_read_failed", path=str(target), err=str(exc))
        return None


# ---------------------------------------------------------------------------
# API client helpers
# ---------------------------------------------------------------------------
def _agent_headers(config: Config) -> dict[str, str]:
    secret = config.agent_shared_secret
    return {
        "X-Agent-Secret": secret,
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }


async def _fetch_estimating_estimates(
    client: httpx.AsyncClient, config: Config, limit: int = 50
) -> list[dict[str, Any]]:
    """GET /v1/estimates?status=estimating&limit=N → list of EstimateListItem dicts."""
    try:
        resp = await client.get(
            "/v1/estimates",
            params={"status": "estimating", "limit": limit},
            headers=_agent_headers(config),
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("items") or []
    except Exception as exc:  # noqa: BLE001
        log.error("estimate.poll_failed", err=str(exc))
        return []


async def _fetch_estimate_status(
    client: httpx.AsyncClient, config: Config, upload_id: str
) -> dict[str, Any] | None:
    """GET /v1/estimates/{upload_id}/status → full StatusOut dict."""
    try:
        resp = await client.get(
            f"/v1/estimates/{upload_id}/status",
            headers=_agent_headers(config),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        log.error("estimate.status_fetch_failed", upload_id=upload_id, err=str(exc))
        return None


async def _fetch_classification_artifact(
    client: httpx.AsyncClient,
    config: Config,
    upload_id: str,
    classification_artifact_id: str,
) -> dict[str, Any] | None:
    """Fetch the approved aace_classification artifact from the approval queue.

    Searches approval items with workflow=aace_classification.publish using
    both 'executed' status (normal path after human approval) and 'approved'
    status (intermediate path). Matches by payload.estimate_upload_id or
    payload.artifact.artifact_id.

    Returns the ``payload.artifact`` dict on success, None on failure.
    """
    # Approval items pass through: pending → approved → executed.
    # The estimate stamp happens at execute time, so by the time we're looking
    # for a classification artifact the item is typically 'executed'.
    for status in ("executed", "approved"):
        try:
            resp = await client.get(
                "/v1/approvals",
                params={
                    "workflow": "aace_classification.publish",
                    "status": status,
                    "limit": 200,
                },
                headers=_agent_headers(config),
            )
            resp.raise_for_status()
            data = resp.json()
            items: list[dict[str, Any]] = data.get("items") or []
        except Exception as exc:  # noqa: BLE001
            log.error(
                "estimate.classification_fetch_failed",
                upload_id=upload_id,
                status=status,
                err=str(exc),
            )
            continue

        for item in items:
            payload = item.get("payload") or {}
            # Match by estimate_upload_id (primary convention, same as G.5)
            if str(payload.get("estimate_upload_id", "")) == upload_id:
                artifact = payload.get("artifact")
                if isinstance(artifact, dict):
                    return artifact
            # Fallback: match by payload.artifact.artifact_id
            artifact = payload.get("artifact")
            if isinstance(artifact, dict):
                if str(artifact.get("artifact_id", "")) == classification_artifact_id:
                    return artifact

    log.warning(
        "estimate.classification_artifact_not_found",
        upload_id=upload_id,
        classification_artifact_id=classification_artifact_id,
    )
    return None


# ---------------------------------------------------------------------------
# Core dispatch logic
# ---------------------------------------------------------------------------
async def dispatch_one(
    upload_id: str,
    estimate_status: dict[str, Any],
    *,
    config: Config,
    queue_client: QueueClient,
    blob_root: Path,
    http_client: httpx.AsyncClient,
) -> str | None:
    """Run the estimator-scheduler for one upload and submit to the approval queue.

    Returns the approval_item_id on success, None on failure.
    """
    from app.services.estimator_input import build_estimator_input  # avoid circular at top

    uploaded_files: list[dict[str, Any]] = estimate_status.get("uploaded_files") or []
    project_label: str = estimate_status.get("project_label") or ""
    classification_artifact_id: str = (
        estimate_status.get("classification_artifact_id") or ""
    )

    if not classification_artifact_id:
        raise RuntimeError(
            f"no classification_artifact_id on estimate upload_id={upload_id}; "
            "cannot run estimator without approved classification"
        )

    # Load the approved aace_classification artifact.
    classification_artifact = await _fetch_classification_artifact(
        http_client, config, upload_id, classification_artifact_id
    )
    if classification_artifact is None:
        raise RuntimeError(
            f"could not load classification artifact "
            f"artifact_id={classification_artifact_id} for upload_id={upload_id}"
        )

    # Load extraction results for all files with ok/partial status.
    extraction_results: list[dict[str, Any]] = []
    for f in uploaded_files:
        ext_status = f.get("extraction_status") or ""
        if ext_status not in ("ok", "partial"):
            log.debug(
                "estimate.file_skip",
                upload_id=upload_id,
                filename=f.get("filename"),
                extraction_status=ext_status,
            )
            continue
        filename = f.get("filename") or ""
        blob = _load_extracted_blob(upload_id, filename, blob_root)
        if blob is None:
            log.warning(
                "estimate.blob_missing",
                upload_id=upload_id,
                filename=filename,
            )
            continue
        # Merge size_bytes from manifest (not stored in extraction blob).
        blob["size_bytes"] = f.get("size_bytes") or blob.get("size_bytes") or 0
        extraction_results.append(blob)

    if not extraction_results:
        raise RuntimeError(
            f"no extractable files found for upload_id={upload_id}; "
            "all files had failed/pending extraction status or missing blobs"
        )

    # Derive project_context from classification artifact metadata (best-effort).
    cls_meta: dict[str, Any] = classification_artifact.get("metadata") or {}
    project_context: dict[str, Any] = {
        "estimate_upload_id": upload_id,
    }
    # Carry over any context the classification embedded (geography, type, etc.)
    if "project_context" in cls_meta:
        project_context.update(cls_meta["project_context"])

    # Build estimator input using the shared builder.
    estimator_input = build_estimator_input(
        extraction_results,
        classification_artifact,
        project_label=project_label,
        project_context=project_context,
    )

    log.info(
        "estimate.running_agent",
        upload_id=upload_id,
        file_count=len(extraction_results),
        classification_artifact_id=classification_artifact_id,
    )

    agent = Agent("estimator-scheduler", config=config)
    run: AgentRun = await agent.run(
        estimator_input,
        submit_to_queue=False,  # we'll inject estimate_upload_id before submitting
        prompt_cache=True,
    )

    if run.output is None:
        raise RuntimeError(f"agent returned no output (error={run.error!r})")
    if run.error and run.error != "schema_validation_failed":
        # Hard errors (llm_error, json_extraction, submit_error) are fatal.
        raise RuntimeError(f"agent error: {run.error}")
    if not run.validation_ok:
        log.warning(
            "estimate.validation_warn",
            upload_id=upload_id,
            errors=run.validation_errors[:5],
        )

    # Build the approval item payload with estimate_upload_id injected so
    # _extract_estimate_upload_id and _extract_estimate_artifact_kind both
    # find what they need (same convention as G.5 classification dispatcher).
    approval_payload: dict[str, Any] = {
        "artifact": run.output,  # full cost_schedule_package dict → payload.artifact
        "estimate_upload_id": upload_id,  # → payload.estimate_upload_id
        "context": {"estimate_upload_id": upload_id},  # → payload.context.estimate_upload_id
    }

    # Determine required approvers from lane decision.
    lane = run.lane_decision.lane if run.lane_decision else 2
    required_approvers: list[str] = []
    if lane == 3:
        required_approvers = ["owner", "partner"]
    elif lane == 2:
        required_approvers = ["owner"]

    submit_payload: dict[str, Any] = {
        "agent_id": "estimator-scheduler",
        "agent_version": run.agent_version,
        # workflow = "cost_schedule_package.publish" triggers _is_publish_artifact
        # and eventually on_package_approved when the user approves.
        "workflow": "cost_schedule_package.publish",
        "lane": lane,
        "priority": "normal",
        "target_system": "none",
        "payload": approval_payload,
        "agent_confidence": run.lane_decision.confidence if run.lane_decision else 0.0,
        "agent_reasoning": (
            "; ".join(run.lane_decision.reasons) if run.lane_decision else ""
        ),
        "agent_model": run.model_used,
        "agent_prompt_version": run.prompt_version_hash[:16],
        "agent_input_hash": run.input_hash,
        "agent_output_hash": run.output_hash or "",
        "required_approvers": required_approvers,
    }

    created = await queue_client.create_approval(submit_payload)
    approval_item_id: str | None = created.get("id")

    log.info(
        "estimate.dispatched",
        upload_id=upload_id,
        approval_item_id=approval_item_id,
        lane=lane,
    )
    return approval_item_id


# ---------------------------------------------------------------------------
# Dispatcher daemon
# ---------------------------------------------------------------------------
class EstimatorDispatcher:
    """Polling daemon that runs the estimator-scheduler on estimating uploads.

    Start with ``await dispatcher.start()`` in an async context.
    Signal with ``dispatcher.stop()`` for graceful shutdown.
    """

    def __init__(
        self,
        *,
        config: Config | None = None,
        state_file: Path | None = None,
        poll_interval_s: float | None = None,
        dispatch_requests_dir: Path | None = None,
    ) -> None:
        self.config = config or get_config()
        self.state_file = state_file or _DEFAULT_STATE_FILE_PATH
        self.poll_interval_s = poll_interval_s or float(
            os.environ.get("ESTIMATE_POLL_INTERVAL_SECONDS", _DEFAULT_POLL_INTERVAL_S)
        )
        self.dispatch_requests_dir = (
            dispatch_requests_dir or _DEFAULT_DISPATCH_REQUESTS_DIR
        )
        self._stop_event = asyncio.Event()
        self._state = _load_state(self.state_file)
        self._blob_root = _blob_root(self.config)

    def stop(self) -> None:
        self._stop_event.set()

    def _is_dispatched(self, upload_id: str) -> bool:
        return upload_id in self._state.dispatched

    def _get_error_entry(self, upload_id: str) -> _ErrorEntry | None:
        for e in self._state.errors:
            if e.upload_id == upload_id:
                return e
        return None

    def _remove_error(self, upload_id: str) -> None:
        self._state.errors = [
            e for e in self._state.errors if e.upload_id != upload_id
        ]

    def _record_success(self, upload_id: str, approval_item_id: str | None) -> None:
        self._remove_error(upload_id)
        self._state.dispatched[upload_id] = _DispatchedEntry(
            upload_id=upload_id,
            dispatched_at=_utcnow_iso(),
            approval_item_id=approval_item_id,
        )
        _save_state(self._state, self.state_file)

    def _record_error(self, upload_id: str, error: str) -> None:
        existing = self._get_error_entry(upload_id)
        attempt = (existing.attempt + 1) if existing else 1
        entry = _ErrorEntry(
            upload_id=upload_id,
            error=error,
            failed_at=_utcnow_iso(),
            retry_after=_retry_after(attempt),
            attempt=attempt,
        )
        self._remove_error(upload_id)
        self._state.errors.append(entry)
        _save_state(self._state, self.state_file)

    def _priority_upload_ids(self) -> set[str]:
        """Scan the dispatch_requests directory for priority markers."""
        if not self.dispatch_requests_dir.exists():
            return set()
        ids: set[str] = set()
        for f in self.dispatch_requests_dir.glob("*.json"):
            upload_id = f.stem
            if upload_id:
                ids.add(upload_id)
        return ids

    async def _tick(
        self,
        http_client: httpx.AsyncClient,
        queue_client: QueueClient,
    ) -> None:
        """One poll cycle: fetch estimating uploads, dispatch any new ones."""
        estimates = await _fetch_estimating_estimates(http_client, self.config)
        priority_ids = self._priority_upload_ids()

        # Combine: estimating estimates + any priority-requested ones not in list
        upload_ids: list[str] = [e["upload_id"] for e in estimates]
        for uid in priority_ids:
            if uid not in upload_ids:
                upload_ids.append(uid)

        for upload_id in upload_ids:
            # Skip already dispatched.
            if self._is_dispatched(upload_id):
                _cleanup_priority_marker(self.dispatch_requests_dir, upload_id)
                continue

            # Check retry back-off for errored uploads.
            err_entry = self._get_error_entry(upload_id)
            if err_entry and not _is_retryable(err_entry):
                log.debug(
                    "estimate.backoff",
                    upload_id=upload_id,
                    retry_after=err_entry.retry_after,
                )
                continue

            # Fetch full status (need uploaded_files manifest +
            # classification_artifact_id).
            status = await _fetch_estimate_status(http_client, self.config, upload_id)
            if status is None:
                continue

            # Guard: skip if already has a package (race condition / restart).
            if status.get("package_artifact_id") is not None:
                log.info(
                    "estimate.already_packaged",
                    upload_id=upload_id,
                )
                # Treat as dispatched to avoid retrying.
                self._record_success(upload_id, approval_item_id=None)
                _cleanup_priority_marker(self.dispatch_requests_dir, upload_id)
                continue

            # Guard: must be in 'estimating' status.
            if status.get("status") != "estimating":
                log.debug(
                    "estimate.not_estimating",
                    upload_id=upload_id,
                    status=status.get("status"),
                )
                continue

            # Guard: must have a classification to work from.
            if not status.get("classification_artifact_id"):
                log.warning(
                    "estimate.missing_classification",
                    upload_id=upload_id,
                )
                continue

            # Dispatch!
            try:
                approval_item_id = await dispatch_one(
                    upload_id,
                    status,
                    config=self.config,
                    queue_client=queue_client,
                    blob_root=self._blob_root,
                    http_client=http_client,
                )
                self._record_success(upload_id, approval_item_id)
                _cleanup_priority_marker(self.dispatch_requests_dir, upload_id)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "estimate.dispatch_failed",
                    upload_id=upload_id,
                    err=str(exc),
                )
                self._record_error(upload_id, str(exc))

    async def start(self) -> None:
        """Main loop. Runs until ``stop()`` is called or SIGTERM/SIGINT."""
        log.info(
            "estimate.dispatcher.start",
            poll_interval_s=self.poll_interval_s,
            state_file=str(self.state_file),
            api_url=self.config.queue_api_url,
        )
        async with httpx.AsyncClient(
            base_url=self.config.queue_api_url,
            timeout=self.config.request_timeout_s,
        ) as http_client, QueueClient(self.config) as queue_client:
            while not self._stop_event.is_set():
                try:
                    await self._tick(http_client, queue_client)
                except Exception as exc:  # noqa: BLE001
                    log.error("estimate.tick_error", err=str(exc))

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.poll_interval_s
                    )
                except asyncio.TimeoutError:
                    continue  # normal: poll interval elapsed

        log.info(
            "estimate.dispatcher.stop",
            dispatched_total=len(self._state.dispatched),
            errors_total=len(self._state.errors),
        )

    def get_status_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable status summary for ``estimate status``."""
        self._state = _load_state(self.state_file)  # re-read fresh
        dispatched_list = sorted(
            self._state.dispatched.values(),
            key=lambda e: e.dispatched_at,
            reverse=True,
        )
        return {
            "dispatched_count": len(dispatched_list),
            "error_count": len(self._state.errors),
            "recent_dispatched": [
                {
                    "upload_id": e.upload_id,
                    "dispatched_at": e.dispatched_at,
                    "approval_item_id": e.approval_item_id,
                }
                for e in dispatched_list[:10]
            ],
            "recent_errors": [
                {
                    "upload_id": e.upload_id,
                    "error": e.error,
                    "failed_at": e.failed_at,
                    "retry_after": e.retry_after,
                    "attempt": e.attempt,
                }
                for e in self._state.errors[-10:]
            ],
        }


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------
def _cleanup_priority_marker(requests_dir: Path, upload_id: str) -> None:
    marker = requests_dir / f"{upload_id}.json"
    try:
        if marker.exists():
            marker.unlink()
    except Exception:  # noqa: BLE001
        pass


def install_signal_handlers(dispatcher: EstimatorDispatcher) -> None:
    """Wire SIGTERM and SIGINT to a graceful stop."""

    def _handle(signum: int, _frame: Any) -> None:
        log.info("estimate.signal_received", signal=signum)
        dispatcher.stop()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


__all__ = [
    "EstimatorDispatcher",
    "DispatcherState",
    "dispatch_one",
    "install_signal_handlers",
]
