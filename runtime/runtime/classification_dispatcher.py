"""ClassificationDispatcher — Phase G.5.

Polling daemon that picks up estimate uploads in ``status='queued'`` and
runs the ``design-classifier`` agent on them, producing an
``aace_classification`` approval item linked to the estimate via
``payload.estimate_upload_id``.

Design goals (mirrors TriageDispatcher):
- **Polling-resilient.** State file persists dispatched upload_ids across
  restarts.
- **Idempotent.** Same upload_id is only dispatched once.
- **Crash-safe.** State file is written atomically (tmp→rename).
- **Graceful shutdown.** Handles SIGTERM / SIGINT without data loss.
- **Configurable poll interval.** ``CLASSIFY_POLL_INTERVAL_SECONDS`` env var.

State file location:
    ``runtime/_state/classification_dispatched.json``

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
                "retry_after": "<iso>"
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
from runtime.state_store import DispatchStateStore, store_from_env

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_POLL_INTERVAL_S = 10.0
_DEFAULT_STATE_FILE_PATH = Path(__file__).resolve().parents[2] / "_state" / "classification_dispatched.json"
_DEFAULT_DISPATCH_REQUESTS_DIR = Path(__file__).resolve().parents[2] / "_state" / "dispatch_requests"

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
        log.warning("classify.state_load_failed", err=str(exc))
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
# Blob reading
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
        log.warning("classify.blob_path_escape", key=key)
        return None
    if not target.exists():
        log.warning("classify.extracted_blob_not_found", path=str(target))
        return None
    try:
        raw = target.read_bytes()
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("classify.blob_read_failed", path=str(target), err=str(exc))
        return None


# ---------------------------------------------------------------------------
# API client helpers (estimates API, not approval queue)
# ---------------------------------------------------------------------------
def _agent_headers(config: Config) -> dict[str, str]:
    secret = config.agent_shared_secret
    return {
        "X-Agent-Secret": secret,
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }


async def _fetch_extracted_blob_api(
    client: httpx.AsyncClient,
    config: Config,
    upload_id: str,
    filename: str,
) -> dict[str, Any] | None:
    """Fallback: fetch the extraction artifact over HTTP (Sprint 4).

    Used when the daemon runs on a different host than the API and the
    blob is not on the local filesystem.
    """
    from urllib.parse import quote

    try:
        resp = await client.get(
            f"/v1/estimates/{upload_id}/extracted/{quote(filename, safe='')}",
            headers=_agent_headers(config),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "classify.remote_blob_fetch_failed",
            upload_id=upload_id,
            filename=filename,
            err=str(exc),
        )
        return None


async def _fetch_queued_estimates(
    client: httpx.AsyncClient, config: Config, limit: int = 50
) -> list[dict[str, Any]]:
    """GET /v1/estimates?status=queued&limit=N → list of EstimateListItem dicts."""
    try:
        resp = await client.get(
            "/v1/estimates",
            params={"status": "queued", "limit": limit},
            headers=_agent_headers(config),
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("items") or []
    except Exception as exc:  # noqa: BLE001
        log.error("classify.poll_failed", err=str(exc))
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
        log.error("classify.status_fetch_failed", upload_id=upload_id, err=str(exc))
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
    http_client: httpx.AsyncClient | None = None,
) -> str | None:
    """Run the design-classifier for one upload and submit to the approval queue.

    Returns the approval_item_id on success, None on failure.
    """
    from app.services.classifier_input import build_classifier_input  # avoid circular at top

    uploaded_files: list[dict[str, Any]] = estimate_status.get("uploaded_files") or []
    project_label: str = estimate_status.get("project_label") or ""
    notes: str = estimate_status.get("notes") or ""

    # Load extraction results for all files with ok/partial status.
    extraction_results: list[dict[str, Any]] = []
    for f in uploaded_files:
        ext_status = f.get("extraction_status") or ""
        if ext_status not in ("ok", "partial"):
            log.debug(
                "classify.file_skip",
                upload_id=upload_id,
                filename=f.get("filename"),
                extraction_status=ext_status,
            )
            continue
        filename = f.get("filename") or ""
        blob = _load_extracted_blob(upload_id, filename, blob_root)
        if blob is None and http_client is not None:
            # Sprint 4: daemon may run on a different host than the API —
            # fall back to fetching the artifact over HTTP.
            blob = await _fetch_extracted_blob_api(
                http_client, config, upload_id, filename
            )
        if blob is None:
            log.warning(
                "classify.blob_missing",
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

    # Build classifier input using the shared builder.
    classifier_input = build_classifier_input(
        extraction_results,
        project_label=project_label,
        notes=notes,
        context={"estimate_upload_id": upload_id},
    )

    log.info(
        "classify.running_agent",
        upload_id=upload_id,
        file_count=len(extraction_results),
    )

    agent = Agent("design-classifier", config=config)
    run: AgentRun = await agent.run(
        classifier_input,
        submit_to_queue=False,  # we'll inject estimate_upload_id before submitting
        prompt_cache=True,
    )

    if run.output is None:
        raise RuntimeError(f"agent returned no output (error={run.error!r})")
    if run.error and run.error != "schema_validation_failed":
        # Hard errors (llm_error, json_extraction, submit_error) are fatal.
        raise RuntimeError(f"agent error: {run.error}")
    if not run.validation_ok:
        # Soft validation failures (e.g. citation field mismatches) are logged
        # as warnings but do not block dispatch. The core artifact fields
        # (artifact_type, class, confidence, body_markdown) are still present.
        log.warning(
            "classify.validation_warn",
            upload_id=upload_id,
            errors=run.validation_errors[:5],
        )

    # Build the approval item payload with estimate_upload_id injected so
    # _extract_estimate_upload_id and _extract_estimate_artifact_kind both
    # find what they need.
    approval_payload: dict[str, Any] = {
        "artifact": run.output,  # full aace_classification dict → payload.artifact
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
        "agent_id": "design-classifier",
        "agent_version": run.agent_version,
        # workflow = "aace_classification.publish" triggers _is_publish_artifact
        # and eventually on_classification_approved when the user approves.
        "workflow": "aace_classification.publish",
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
        "classify.dispatched",
        upload_id=upload_id,
        approval_item_id=approval_item_id,
        lane=lane,
    )
    return approval_item_id


# ---------------------------------------------------------------------------
# Dispatcher daemon
# ---------------------------------------------------------------------------
class ClassificationDispatcher:
    """Polling daemon that classifies queued estimates.

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
        state_store: DispatchStateStore | None = None,
    ) -> None:
        self.config = config or get_config()
        self.state_file = state_file or _DEFAULT_STATE_FILE_PATH
        self.poll_interval_s = poll_interval_s or float(
            os.environ.get("CLASSIFY_POLL_INTERVAL_SECONDS", _DEFAULT_POLL_INTERVAL_S)
        )
        self.dispatch_requests_dir = (
            dispatch_requests_dir or _DEFAULT_DISPATCH_REQUESTS_DIR
        )
        self._stop_event = asyncio.Event()
        self._state = _load_state(self.state_file)
        self._blob_root = _blob_root(self.config)
        # Sprint 5.5 — optional shared state store (Postgres in the Cloud Run
        # worker). When None, the legacy JSON state file is used unchanged.
        self._store = state_store if state_store is not None else store_from_env(
            "classification"
        )

    def stop(self) -> None:
        self._stop_event.set()

    # ------------------------------------------------------------------
    # State-store seam (Sprint 5.5) — see contract_dispatcher for details.
    # ------------------------------------------------------------------
    async def _claim(self, upload_id: str) -> bool:
        if self._store is not None:
            return await self._store.try_claim(upload_id)
        if self._is_dispatched(upload_id):
            return False
        err_entry = self._get_error_entry(upload_id)
        if err_entry and not _is_retryable(err_entry):
            log.debug(
                "classify.backoff",
                upload_id=upload_id,
                retry_after=err_entry.retry_after,
            )
            return False
        return True

    async def _is_done(self, upload_id: str) -> bool:
        if self._store is not None:
            return await self._store.is_done(upload_id)
        return self._is_dispatched(upload_id)

    async def _unclaim(self, upload_id: str) -> None:
        if self._store is not None:
            await self._store.release_claim(upload_id)

    async def _mark_success(
        self, upload_id: str, approval_item_id: str | None
    ) -> None:
        if self._store is not None:
            await self._store.record_success(upload_id, approval_item_id)
        else:
            self._record_success(upload_id, approval_item_id)

    async def _mark_error(self, upload_id: str, error: str) -> None:
        if self._store is not None:
            await self._store.record_error(upload_id, error)
        else:
            self._record_error(upload_id, error)

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
        """One poll cycle: fetch queued estimates, dispatch any new ones."""
        estimates = await _fetch_queued_estimates(http_client, self.config)
        priority_ids = self._priority_upload_ids()

        # Combine: queued estimates + any priority-requested ones not in list
        upload_ids: list[str] = [e["upload_id"] for e in estimates]
        for uid in priority_ids:
            if uid not in upload_ids:
                upload_ids.append(uid)

        for upload_id in upload_ids:
            # Skip already dispatched.
            if not await self._claim(upload_id):
                if await self._is_done(upload_id):
                    # Clean up priority marker if present.
                    _cleanup_priority_marker(self.dispatch_requests_dir, upload_id)
                continue

            # Fetch full status (need uploaded_files manifest).
            status = await _fetch_estimate_status(http_client, self.config, upload_id)
            if status is None:
                await self._unclaim(upload_id)
                continue

            # Guard: skip if already has a classification (race condition).
            if status.get("classification_artifact_id") is not None:
                log.info(
                    "classify.already_classified",
                    upload_id=upload_id,
                )
                # Treat as dispatched to avoid retrying.
                await self._mark_success(upload_id, approval_item_id=None)
                _cleanup_priority_marker(self.dispatch_requests_dir, upload_id)
                continue

            if status.get("status") != "queued":
                log.debug(
                    "classify.not_queued",
                    upload_id=upload_id,
                    status=status.get("status"),
                )
                await self._unclaim(upload_id)
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
                await self._mark_success(upload_id, approval_item_id)
                _cleanup_priority_marker(self.dispatch_requests_dir, upload_id)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "classify.dispatch_failed",
                    upload_id=upload_id,
                    err=str(exc),
                )
                await self._mark_error(upload_id, str(exc))

    async def start(self) -> None:
        """Main loop. Runs until ``stop()`` is called or SIGTERM/SIGINT."""
        log.info(
            "classify.dispatcher.start",
            poll_interval_s=self.poll_interval_s,
            state_file=str(self.state_file),
            state_backend="postgres" if self._store is not None else "file",
            api_url=self.config.queue_api_url,
        )
        if self._store is not None:
            await self._store.setup()
        async with httpx.AsyncClient(
            base_url=self.config.queue_api_url,
            timeout=self.config.request_timeout_s,
        ) as http_client, QueueClient(self.config) as queue_client:
            while not self._stop_event.is_set():
                try:
                    await self._tick(http_client, queue_client)
                except Exception as exc:  # noqa: BLE001
                    log.error("classify.tick_error", err=str(exc))

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.poll_interval_s
                    )
                except asyncio.TimeoutError:
                    continue  # normal: poll interval elapsed

        log.info(
            "classify.dispatcher.stop",
            dispatched_total=len(self._state.dispatched),
            errors_total=len(self._state.errors),
        )

    def get_status_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable status summary for ``classify status``."""
        if self._store is not None:
            return asyncio.run(self._store.status_summary())
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


def install_signal_handlers(dispatcher: ClassificationDispatcher) -> None:
    """Wire SIGTERM and SIGINT to a graceful stop."""

    def _handle(signum: int, _frame: Any) -> None:
        log.info("classify.signal_received", signal=signum)
        dispatcher.stop()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


__all__ = [
    "ClassificationDispatcher",
    "DispatcherState",
    "dispatch_one",
    "install_signal_handlers",
]
