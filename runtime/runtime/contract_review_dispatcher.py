"""ContractReviewDispatcher — Sprint Contracts.2.

Polling daemon that picks up contracts in ``status='extracted'`` with
``extracted_fields IS NOT NULL`` and ``review_artifact_id IS NULL``, and
runs the ``contract-reviewer`` agent on them, producing a
``contract_review.publish`` approval item linked to the contract via
``payload.contract_upload_id``.

Design mirrors ContractDispatcher (Contracts.1) exactly:
- **Polling-resilient.** State file persists dispatched upload_ids across restarts.
- **Idempotent.** Same upload_id is only dispatched once.
- **Crash-safe.** State file written atomically (tmp→rename).
- **Graceful shutdown.** Handles SIGTERM / SIGINT.
- **Configurable poll interval.** ``CONTRACT_REVIEW_POLL_INTERVAL_SECONDS`` env var.

State file location:
    ``runtime/_state/contract_review_dispatched.json``

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
                "attempt": 1
            }
        ]
    }
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
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
_DEFAULT_POLL_INTERVAL_S = 15.0
_DEFAULT_STATE_FILE_PATH = (
    Path(__file__).resolve().parents[2] / "_state" / "contract_review_dispatched.json"
)
_DEFAULT_REVIEW_REQUESTS_DIR = (
    Path(__file__).resolve().parents[2] / "_state" / "contract_review_requests"
)

_MAX_BACKOFF_S = 5 * 60  # 5 minutes
_INITIAL_BACKOFF_S = 30.0


# ---------------------------------------------------------------------------
# State management (mirrors contract_dispatcher exactly)
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
class ReviewDispatcherState:
    dispatched: dict[str, _DispatchedEntry] = field(default_factory=dict)
    errors: list[_ErrorEntry] = field(default_factory=list)


def _load_state(state_file: Path) -> ReviewDispatcherState:
    if not state_file.exists():
        return ReviewDispatcherState()
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        dispatched = {
            uid: _DispatchedEntry(**entry)
            for uid, entry in raw.get("dispatched", {}).items()
        }
        errors = [_ErrorEntry(**e) for e in raw.get("errors", [])]
        return ReviewDispatcherState(dispatched=dispatched, errors=errors)
    except Exception:  # noqa: BLE001
        log.warning("contract_review.state_load_failed path=%s — starting fresh", state_file)
        return ReviewDispatcherState()


def _save_state(state: ReviewDispatcherState, state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(".tmp")
    raw = {
        "dispatched": {
            uid: {
                "upload_id": e.upload_id,
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
    tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    tmp.replace(state_file)


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _retry_after(attempt: int) -> str:
    backoff = min(_INITIAL_BACKOFF_S * (2 ** (attempt - 1)), _MAX_BACKOFF_S)
    return (datetime.now(UTC) + timedelta(seconds=backoff)).isoformat()


def _is_retryable(entry: _ErrorEntry) -> bool:
    try:
        retry_dt = datetime.fromisoformat(entry.retry_after)
        return datetime.now(UTC) >= retry_dt
    except Exception:  # noqa: BLE001
        return True


# ---------------------------------------------------------------------------
# Blob helpers (mirrors contract_dispatcher)
# ---------------------------------------------------------------------------
def _blob_root(config: Config) -> Path:
    val = (
        getattr(config, "CONTRACTS_BLOB_PATH", None)
        or os.environ.get("CONTRACTS_BLOB_PATH", "./_local_contracts")
    )
    return Path(val).resolve()


def _load_extracted_text(upload_id: str, filename: str, blob_root: Path) -> str | None:
    """Load the plain-text blob written during text-extraction."""
    from re import compile as _re_compile

    _safe_re = _re_compile(r"[^A-Za-z0-9._-]+")
    safe_name = _safe_re.sub("_", filename)
    key = f"contracts/{upload_id}/extracted/{safe_name}.txt"
    target = (blob_root / key).resolve()
    if not str(target).startswith(str(blob_root)):
        return None
    if not target.is_file():
        return None
    try:
        return target.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
async def _fetch_extracted_text_api(
    client: httpx.AsyncClient,
    config: Config,
    upload_id: str,
    filename: str,
) -> str | None:
    """Fallback: fetch the full extracted text over HTTP (Sprint 4).

    Used when the daemon runs on a different host than the API and the
    text blob is not on the local filesystem.
    """
    from urllib.parse import quote

    try:
        resp = await client.get(
            f"/v1/contracts/{upload_id}/extracted/{quote(filename, safe='')}",
            headers={"X-Agent-Secret": config.agent_shared_secret},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "contract_review.remote_text_fetch_failed upload_id=%s file=%s err=%s",
            upload_id,
            filename,
            exc,
        )
        return None


async def _fetch_extracted_contracts(
    http_client: httpx.AsyncClient,
    config: Config,
) -> list[dict[str, Any]]:
    """Fetch contracts with status=extracted from the API."""
    try:
        resp = await http_client.get(
            "/v1/contracts",
            params={"status": "extracted", "limit": 50},
            headers={"X-Agent-Secret": config.agent_shared_secret},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])
    except Exception as exc:  # noqa: BLE001
        log.warning("contract_review.fetch_contracts_failed err=%s", exc)
        return []


async def _fetch_contract(
    http_client: httpx.AsyncClient,
    config: Config,
    upload_id: str,
) -> dict[str, Any] | None:
    """Fetch a single contract's full record."""
    try:
        resp = await http_client.get(
            f"/v1/contracts/{upload_id}",
            headers={"X-Agent-Secret": config.agent_shared_secret},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("contract_review.fetch_contract_failed upload_id=%s err=%s", upload_id, exc)
        return None


def _build_review_input(
    upload_id: str,
    contract_data: dict[str, Any],
    blob_root: Path,
    remote_texts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the contract-reviewer agent input from the contract record.

    ``remote_texts`` maps filename → text fetched over HTTP for files whose
    blobs are not on the local filesystem (Sprint 4 remote-daemon support).
    """
    uploaded_files: list[dict[str, Any]] = contract_data.get("uploaded_files") or []
    project_label: str = contract_data.get("project_label") or ""
    extracted_fields: dict[str, Any] = contract_data.get("extracted_fields") or {}

    raw_text_parts: list[str] = []
    for f in uploaded_files:
        fname = f.get("filename") or ""
        ext_status = f.get("extraction_status") or ""
        if ext_status not in ("ok", "partial"):
            continue
        text = _load_extracted_text(upload_id, fname, blob_root)
        if text is None and remote_texts:
            text = remote_texts.get(fname)
        if text is None:
            text = f.get("extraction_summary") or ""
        if text:
            raw_text_parts.append(text)

    raw_text = "\n\n".join(raw_text_parts)

    if not raw_text:
        # Fall back to extraction summary
        raw_text = extracted_fields.get("plain_english_summary", "")

    return {
        "upload_id": upload_id,
        "project_label": project_label,
        "extraction": extracted_fields,
        "raw_text": raw_text[:40000],  # cap to avoid token overrun
        "context": {"contract_upload_id": upload_id},
    }


# ---------------------------------------------------------------------------
# Core dispatch function
# ---------------------------------------------------------------------------
async def dispatch_one_review(
    upload_id: str,
    contract_data: dict[str, Any],
    *,
    config: Config,
    queue_client: QueueClient,
    blob_root: Path,
    http_client: httpx.AsyncClient | None = None,
) -> str | None:
    """Run the contract-reviewer for one upload and submit to the approval queue.

    Returns the approval_item_id on success, None on failure.
    """
    remote_texts: dict[str, str] = {}
    if http_client is not None:
        for f in contract_data.get("uploaded_files") or []:
            fname = f.get("filename") or ""
            if (f.get("extraction_status") or "") not in ("ok", "partial"):
                continue
            if _load_extracted_text(upload_id, fname, blob_root) is not None:
                continue
            text = await _fetch_extracted_text_api(
                http_client, config, upload_id, fname
            )
            if text:
                remote_texts[fname] = text

    agent_input = _build_review_input(
        upload_id, contract_data, blob_root, remote_texts=remote_texts
    )

    log.info(
        "contract_review.running_agent",
        upload_id=upload_id,
    )

    agent = Agent("contract-reviewer", config=config)
    run: AgentRun = await agent.run(
        agent_input,
        submit_to_queue=False,
        prompt_cache=True,
    )

    if run.output is None:
        raise RuntimeError(f"agent returned no output (error={run.error!r})")
    if run.error and run.error not in ("schema_validation_failed",):
        raise RuntimeError(f"agent error: {run.error}")
    if not run.validation_ok:
        log.warning(
            "contract_review.validation_warn",
            upload_id=upload_id,
            errors=(run.validation_errors or [])[:5],
        )

    approval_payload: dict[str, Any] = {
        "artifact": run.output,
        "contract_upload_id": upload_id,
        "context": {"contract_upload_id": upload_id},
    }

    lane = run.lane_decision.lane if run.lane_decision else 2
    required_approvers: list[str] = []
    if lane == 3:
        required_approvers = ["owner", "partner"]
    elif lane == 2:
        required_approvers = ["owner"]

    submit_payload: dict[str, Any] = {
        "agent_id": "contract-reviewer",
        "agent_version": run.agent_version,
        "workflow": "contract_review.publish",
        "lane": lane,
        "priority": "normal",
        "target_system": "none",
        "payload": approval_payload,
        "agent_confidence": run.lane_decision.confidence if run.lane_decision else 0.0,
        "agent_reasoning": (
            "; ".join(run.lane_decision.reasons) if run.lane_decision else ""
        ),
        "agent_model": run.model_used,
        "agent_prompt_version": (run.prompt_version_hash or "")[:16],
        "agent_input_hash": run.input_hash,
        "agent_output_hash": run.output_hash or "",
        "required_approvers": required_approvers,
    }

    created = await queue_client.create_approval(submit_payload)
    approval_item_id: str | None = created.get("id")

    log.info(
        "contract_review.dispatched",
        upload_id=upload_id,
        approval_item_id=approval_item_id,
        lane=lane,
    )
    return approval_item_id


# ---------------------------------------------------------------------------
# Dispatcher daemon
# ---------------------------------------------------------------------------
class ContractReviewDispatcher:
    """Polling daemon that reviews extracted contracts.

    Polls for contracts where:
    - status == 'extracted'
    - extracted_fields IS NOT NULL
    - review_artifact_id IS NULL

    For each such contract, runs contract-reviewer and submits a
    contract_review.publish approval item.
    """

    def __init__(
        self,
        *,
        config: Config | None = None,
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
        state_file: Path | None = None,
        review_requests_dir: Path | None = None,
    ) -> None:
        self.config = config or get_config()
        self.poll_interval_s = poll_interval_s
        self.state_file = state_file or _DEFAULT_STATE_FILE_PATH
        self.review_requests_dir = review_requests_dir or _DEFAULT_REVIEW_REQUESTS_DIR
        self._state = _load_state(self.state_file)
        self._stop_event = asyncio.Event()
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
        """Scan the review_requests directory for priority markers."""
        if not self.review_requests_dir.exists():
            return set()
        ids: set[str] = set()
        for f in self.review_requests_dir.glob("*.json"):
            upload_id = f.stem
            if upload_id:
                ids.add(upload_id)
        return ids

    async def _tick(
        self,
        http_client: httpx.AsyncClient,
        queue_client: QueueClient,
    ) -> None:
        """One poll cycle."""
        contracts = await _fetch_extracted_contracts(http_client, self.config)
        priority_ids = self._priority_upload_ids()

        upload_ids: list[str] = [c["upload_id"] for c in contracts]
        for uid in priority_ids:
            if uid not in upload_ids:
                upload_ids.append(uid)

        for upload_id in upload_ids:
            if self._is_dispatched(upload_id):
                _cleanup_priority_marker(self.review_requests_dir, upload_id)
                continue

            err_entry = self._get_error_entry(upload_id)
            if err_entry and not _is_retryable(err_entry):
                log.debug(
                    "contract_review.backoff",
                    upload_id=upload_id,
                    retry_after=err_entry.retry_after,
                )
                continue

            contract_data = await _fetch_contract(http_client, self.config, upload_id)
            if contract_data is None:
                continue

            # Guard: skip if already has a review artifact (race condition).
            if contract_data.get("review_artifact_id") is not None:
                log.info("contract_review.already_reviewed", upload_id=upload_id)
                self._record_success(upload_id, approval_item_id=None)
                _cleanup_priority_marker(self.review_requests_dir, upload_id)
                continue

            # Guard: must have extracted_fields.
            if contract_data.get("extracted_fields") is None:
                log.debug(
                    "contract_review.no_extraction",
                    upload_id=upload_id,
                )
                continue

            if contract_data.get("status") != "extracted":
                log.debug(
                    "contract_review.not_extracted",
                    upload_id=upload_id,
                    status=contract_data.get("status"),
                )
                continue

            try:
                approval_item_id = await dispatch_one_review(
                    upload_id,
                    contract_data,
                    config=self.config,
                    queue_client=queue_client,
                    blob_root=self._blob_root,
                    http_client=http_client,
                )
                self._record_success(upload_id, approval_item_id)
                _cleanup_priority_marker(self.review_requests_dir, upload_id)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "contract_review.dispatch_failed",
                    upload_id=upload_id,
                    err=str(exc),
                )
                self._record_error(upload_id, str(exc))

    async def start(self) -> None:
        """Main loop. Runs until ``stop()`` is called or SIGTERM/SIGINT."""
        log.info(
            "contract_review.dispatcher.start",
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
                    log.error("contract_review.tick_error", err=str(exc))

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.poll_interval_s
                    )
                except asyncio.TimeoutError:
                    continue

        log.info(
            "contract_review.dispatcher.stop",
            dispatched_total=len(self._state.dispatched),
            errors_total=len(self._state.errors),
        )

    def get_status_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable status summary."""
        self._state = _load_state(self.state_file)
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


def install_review_signal_handlers(dispatcher: ContractReviewDispatcher) -> None:
    """Wire SIGTERM and SIGINT to a graceful stop."""

    def _handle(signum: int, _frame: Any) -> None:
        log.info("contract_review.signal_received", signal=signum)
        dispatcher.stop()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


__all__ = [
    "ContractReviewDispatcher",
    "ReviewDispatcherState",
    "dispatch_one_review",
    "install_review_signal_handlers",
]
