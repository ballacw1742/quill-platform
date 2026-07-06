"""ContractDispatcher — Sprint Contracts.1.

Polling daemon that picks up contract uploads in ``status='extracted'`` and
runs the ``contract-extractor`` agent on them, producing a
``contract_extraction.publish`` approval item linked to the contract via
``payload.contract_upload_id``.

Design mirrors ClassificationDispatcher exactly:
- **Polling-resilient.** State file persists dispatched upload_ids across restarts.
- **Idempotent.** Same upload_id is only dispatched once.
- **Crash-safe.** State file written atomically (tmp→rename).
- **Graceful shutdown.** Handles SIGTERM / SIGINT.
- **Configurable poll interval.** ``CONTRACT_POLL_INTERVAL_SECONDS`` env var.

State file location:
    ``runtime/_state/contract_dispatched.json``

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
_DEFAULT_POLL_INTERVAL_S = 10.0
_DEFAULT_STATE_FILE_PATH = (
    Path(__file__).resolve().parents[2] / "_state" / "contract_dispatched.json"
)
_DEFAULT_DISPATCH_REQUESTS_DIR = (
    Path(__file__).resolve().parents[2] / "_state" / "contract_dispatch_requests"
)

_MAX_BACKOFF_S = 5 * 60  # 5 minutes
_INITIAL_BACKOFF_S = 30.0


# ---------------------------------------------------------------------------
# State management (mirrors classification_dispatcher exactly)
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
        log.warning("contract.state_load_failed", err=str(exc))
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
    return min(_INITIAL_BACKOFF_S * (2 ** (attempt - 1)), _MAX_BACKOFF_S)


def _retry_after(attempt: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=_backoff_for(attempt))).isoformat()


def _is_retryable(error_entry: _ErrorEntry) -> bool:
    try:
        ra = datetime.fromisoformat(error_entry.retry_after)
        return datetime.now(UTC) >= ra
    except Exception:  # noqa: BLE001
        return True


# ---------------------------------------------------------------------------
# Blob reading
# ---------------------------------------------------------------------------
def _blob_root(config: Config) -> Path:
    raw = os.environ.get("CONTRACTS_BLOB_PATH", "./_local_contracts")
    return Path(raw).resolve()


def _load_extracted_text(
    upload_id: str, filename: str, blob_root: Path
) -> str | None:
    """Load a per-file extracted text from blob storage."""
    import re as _re

    safe_name = _re.sub(r"[^A-Za-z0-9._-]+", "_", filename)[:128]
    key = f"contracts/{upload_id}/extracted/{safe_name}.txt"
    target = (blob_root / key).resolve()
    if not str(target).startswith(str(blob_root)):
        log.warning("contract.blob_path_escape", key=key)
        return None
    if not target.exists():
        log.warning("contract.extracted_blob_not_found", path=str(target))
        return None
    try:
        return target.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log.warning("contract.blob_read_failed", path=str(target), err=str(exc))
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
            headers=_agent_headers(config),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "contract.remote_text_fetch_failed",
            upload_id=upload_id,
            filename=filename,
            err=str(exc),
        )
        return None


async def _fetch_extracted_contracts(
    client: httpx.AsyncClient, config: Config, limit: int = 50
) -> list[dict[str, Any]]:
    """GET /v1/contracts?status=extracted&limit=N → list of ContractListItem dicts."""
    try:
        resp = await client.get(
            "/v1/contracts",
            params={"status": "extracted", "limit": limit},
            headers=_agent_headers(config),
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("items") or []
    except Exception as exc:  # noqa: BLE001
        log.error("contract.poll_failed", err=str(exc))
        return []


async def _fetch_contract(
    client: httpx.AsyncClient, config: Config, upload_id: str
) -> dict[str, Any] | None:
    """GET /v1/contracts/{upload_id} → full ContractOut dict."""
    try:
        resp = await client.get(
            f"/v1/contracts/{upload_id}",
            headers=_agent_headers(config),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        log.error("contract.fetch_failed", upload_id=upload_id, err=str(exc))
        return None


async def _update_contract_extracted_fields(
    client: httpx.AsyncClient,
    config: Config,
    upload_id: str,
    extracted_fields: dict[str, Any],
) -> None:
    """PATCH extracted fields back to the contract via the API.

    Note: We call the internal audit-aware path via the service layer.
    In v0.1, this is done via a dedicated internal endpoint; for now we
    patch by calling mark_status to 'extracted' (idempotent) so the daemon
    can at least track progress. The full field update happens via the
    on_extraction_approved hook when the approval is approved.
    """
    # We don't have a PATCH endpoint in v0.1. The field update happens
    # through the approval pipeline. Log the intention for debugging.
    log.info(
        "contract.extracted_fields_pending_approval",
        upload_id=upload_id,
        artifact_type=extracted_fields.get("artifact_type"),
    )


# ---------------------------------------------------------------------------
# Core dispatch logic
# ---------------------------------------------------------------------------
def _build_agent_input(
    upload_id: str,
    contract_data: dict[str, Any],
    blob_root: Path,
    remote_texts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the agent input from the contract record and extracted text blobs.

    ``remote_texts`` maps filename → text fetched over HTTP for files whose
    blobs are not on the local filesystem (Sprint 4 remote-daemon support).
    """
    uploaded_files: list[dict[str, Any]] = contract_data.get("uploaded_files") or []
    project_label: str = contract_data.get("project_label") or ""
    notes: str = contract_data.get("notes") or ""

    files_input: list[dict[str, Any]] = []
    for f in uploaded_files:
        fname = f.get("filename") or ""
        kind = f.get("kind") or "other"
        ext_status = f.get("extraction_status") or ""
        if ext_status not in ("ok", "partial"):
            log.debug(
                "contract.file_skip",
                upload_id=upload_id,
                filename=fname,
                extraction_status=ext_status,
            )
            continue
        text = _load_extracted_text(upload_id, fname, blob_root)
        if text is None and remote_texts:
            text = remote_texts.get(fname)
        if text is None:
            log.warning(
                "contract.text_blob_missing",
                upload_id=upload_id,
                filename=fname,
            )
            text = f.get("extraction_summary") or ""
        files_input.append(
            {
                "filename": fname,
                "kind": kind,
                "extracted_text": text,
            }
        )

    if not files_input:
        raise RuntimeError(
            f"no extractable files found for upload_id={upload_id}; "
            "all files had failed/pending extraction status or missing text blobs"
        )

    return {
        "upload_id": upload_id,
        "project_label": project_label,
        "notes": notes,
        "context": {"contract_upload_id": upload_id},
        "files": files_input,
    }


async def dispatch_one(
    upload_id: str,
    contract_data: dict[str, Any],
    *,
    config: Config,
    queue_client: QueueClient,
    blob_root: Path,
    http_client: httpx.AsyncClient | None = None,
) -> str | None:
    """Run the contract-extractor for one upload and submit to the approval queue.

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

    agent_input = _build_agent_input(
        upload_id, contract_data, blob_root, remote_texts=remote_texts
    )

    log.info(
        "contract.running_agent",
        upload_id=upload_id,
        file_count=len(agent_input["files"]),
    )

    agent = Agent("contract-extractor", config=config)
    run: AgentRun = await agent.run(
        agent_input,
        submit_to_queue=False,  # we inject contract_upload_id before submitting
        prompt_cache=True,
    )

    if run.output is None:
        raise RuntimeError(f"agent returned no output (error={run.error!r})")
    if run.error and run.error not in ("schema_validation_failed",):
        raise RuntimeError(f"agent error: {run.error}")
    if not run.validation_ok:
        log.warning(
            "contract.validation_warn",
            upload_id=upload_id,
            errors=(run.validation_errors or [])[:5],
        )

    # Build the approval payload with contract_upload_id injected in both
    # payload.contract_upload_id and payload.context.contract_upload_id
    # (mirrors the estimate pattern for estimate_upload_id).
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
        "agent_id": "contract-extractor",
        "agent_version": run.agent_version,
        "workflow": "contract_extraction.publish",
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
        "contract.dispatched",
        upload_id=upload_id,
        approval_item_id=approval_item_id,
        lane=lane,
    )
    return approval_item_id


# ---------------------------------------------------------------------------
# Dispatcher daemon
# ---------------------------------------------------------------------------
class ContractDispatcher:
    """Polling daemon that extracts fields from extracted contracts.

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
            os.environ.get("CONTRACT_POLL_INTERVAL_SECONDS", _DEFAULT_POLL_INTERVAL_S)
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
        """One poll cycle: fetch extracted contracts, dispatch any new ones."""
        contracts = await _fetch_extracted_contracts(http_client, self.config)
        priority_ids = self._priority_upload_ids()

        upload_ids: list[str] = [c["upload_id"] for c in contracts]
        for uid in priority_ids:
            if uid not in upload_ids:
                upload_ids.append(uid)

        for upload_id in upload_ids:
            if self._is_dispatched(upload_id):
                _cleanup_priority_marker(self.dispatch_requests_dir, upload_id)
                continue

            err_entry = self._get_error_entry(upload_id)
            if err_entry and not _is_retryable(err_entry):
                log.debug(
                    "contract.backoff",
                    upload_id=upload_id,
                    retry_after=err_entry.retry_after,
                )
                continue

            contract_data = await _fetch_contract(http_client, self.config, upload_id)
            if contract_data is None:
                continue

            # Guard: skip if already has extracted_fields (race condition).
            if contract_data.get("extracted_fields") is not None:
                log.info("contract.already_extracted", upload_id=upload_id)
                self._record_success(upload_id, approval_item_id=None)
                _cleanup_priority_marker(self.dispatch_requests_dir, upload_id)
                continue

            if contract_data.get("status") != "extracted":
                log.debug(
                    "contract.not_extracted",
                    upload_id=upload_id,
                    status=contract_data.get("status"),
                )
                continue

            try:
                approval_item_id = await dispatch_one(
                    upload_id,
                    contract_data,
                    config=self.config,
                    queue_client=queue_client,
                    blob_root=self._blob_root,
                    http_client=http_client,
                )
                self._record_success(upload_id, approval_item_id)
                _cleanup_priority_marker(self.dispatch_requests_dir, upload_id)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "contract.dispatch_failed",
                    upload_id=upload_id,
                    err=str(exc),
                )
                self._record_error(upload_id, str(exc))

    async def start(self) -> None:
        """Main loop. Runs until ``stop()`` is called or SIGTERM/SIGINT."""
        log.info(
            "contract.dispatcher.start",
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
                    log.error("contract.tick_error", err=str(exc))

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.poll_interval_s
                    )
                except asyncio.TimeoutError:
                    continue

        log.info(
            "contract.dispatcher.stop",
            dispatched_total=len(self._state.dispatched),
            errors_total=len(self._state.errors),
        )

    def get_status_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable status summary for ``contract status``."""
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


def install_signal_handlers(dispatcher: ContractDispatcher) -> None:
    """Wire SIGTERM and SIGINT to a graceful stop."""

    def _handle(signum: int, _frame: Any) -> None:
        log.info("contract.signal_received", signal=signum)
        dispatcher.stop()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


__all__ = [
    "ContractDispatcher",
    "DispatcherState",
    "dispatch_one",
    "install_signal_handlers",
]
