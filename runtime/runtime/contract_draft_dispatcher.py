"""ContractDraftDispatcher — Sprint Contracts.3.

Polling daemon that picks up contracts in ``status='drafting'`` with
``source='drafted'`` and runs the ``contract-drafter`` agent on them,
producing a ``contract_draft.publish`` approval item linked to the contract
via ``payload.contract_upload_id``.

Design mirrors ContractReviewDispatcher (Contracts.2) exactly:
- **Polling-resilient.** State file persists dispatched upload_ids across restarts.
- **Idempotent.** Same upload_id is only dispatched once.
- **Crash-safe.** State file written atomically (tmp→rename).
- **Graceful shutdown.** Handles SIGTERM / SIGINT.
- **Configurable poll interval.** ``CONTRACT_DRAFT_POLL_INTERVAL_SECONDS`` env var.

State file location:
    ``runtime/_state/contract_draft_dispatched.json``

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
    Path(__file__).resolve().parents[2] / "_state" / "contract_draft_dispatched.json"
)
_DEFAULT_DRAFT_REQUESTS_DIR = (
    Path(__file__).resolve().parents[2] / "_state" / "contract_draft_requests"
)

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
class DraftDispatcherState:
    dispatched: dict[str, _DispatchedEntry] = field(default_factory=dict)
    errors: list[_ErrorEntry] = field(default_factory=list)


def _load_state(state_file: Path) -> DraftDispatcherState:
    if not state_file.exists():
        return DraftDispatcherState()
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        dispatched = {
            uid: _DispatchedEntry(**entry)
            for uid, entry in raw.get("dispatched", {}).items()
        }
        errors = [_ErrorEntry(**e) for e in raw.get("errors", [])]
        return DraftDispatcherState(dispatched=dispatched, errors=errors)
    except Exception:  # noqa: BLE001
        log.warning("contract_draft.state_load_failed path=%s — starting fresh", state_file)
        return DraftDispatcherState()


def _save_state(state: DraftDispatcherState, state_file: Path) -> None:
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
# Blob / template helpers
# ---------------------------------------------------------------------------
def _blob_root(config: Config) -> Path:
    val = (
        getattr(config, "CONTRACTS_BLOB_PATH", None)
        or os.environ.get("CONTRACTS_BLOB_PATH", "./_local_contracts")
    )
    return Path(val).resolve()


def _load_template_body(template_id: str) -> str | None:
    """Load the body text for a named contract template from the prompts repo."""
    # Resolve prompts repo from config or via env / relative path
    prompts_root_env = os.environ.get("PROMPTS_REPO_PATH")
    if prompts_root_env:
        prompts_root = Path(prompts_root_env).resolve()
    else:
        # runtime/runtime/ → runtime/ → quill-platform/ → agentic-pmo-prompts/
        prompts_root = Path(__file__).resolve().parents[2] / "agentic-pmo-prompts"

    tmpl_dir = prompts_root / "templates" / "contracts"
    if not tmpl_dir.is_dir():
        log.warning("contract_draft.templates_dir_missing path=%s", tmpl_dir)
        return None

    # Try exact stem match first, then scan for template_id in frontmatter
    for path in tmpl_dir.glob("*.md"):
        if path.name.lower() == "index.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue

        # Quick frontmatter scan
        if text.startswith("---"):
            end_idx = text.find("\n---", 3)
            if end_idx != -1:
                yaml_block = text[3:end_idx]
                if f"template_id: {template_id}" in yaml_block:
                    # Return the body (after the closing ---)
                    return text[end_idx + 4:].lstrip("\n")

        # Fallback: match by stem
        if path.stem == template_id:
            return text

    return None


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
async def _fetch_drafting_contracts(
    http_client: httpx.AsyncClient,
    config: Config,
) -> list[dict[str, Any]]:
    """Fetch contracts with status=drafting and source=drafted from the API."""
    try:
        resp = await http_client.get(
            "/v1/contracts",
            params={"status": "drafting", "source": "drafted", "limit": 50},
            headers={"X-Agent-Secret": config.agent_shared_secret},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])
    except Exception as exc:  # noqa: BLE001
        log.warning("contract_draft.fetch_contracts_failed err=%s", exc)
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
        log.warning(
            "contract_draft.fetch_contract_failed upload_id=%s err=%s", upload_id, exc
        )
        return None


def _build_draft_input(
    upload_id: str,
    contract_data: dict[str, Any],
) -> dict[str, Any]:
    """Build the contract-drafter agent input from the contract record.

    Matches the input schema defined in:
        agentic-pmo-prompts/agents/contract-drafter/agent.md
    """
    draft_request: dict[str, Any] = contract_data.get("draft_request") or {}
    mode: str = contract_data.get("mode") or draft_request.get("mode") or "negotiated"
    template_id: str | None = draft_request.get("template_id")

    # Load template body if mode == template
    template_body: str = ""
    if mode == "template" and template_id:
        body = _load_template_body(template_id)
        if body:
            template_body = body
            log.debug(
                "contract_draft.template_loaded",
                upload_id=upload_id,
                template_id=template_id,
            )
        else:
            log.warning(
                "contract_draft.template_not_found",
                upload_id=upload_id,
                template_id=template_id,
            )

    agent_input: dict[str, Any] = {
        "upload_id": upload_id,
        "mode": mode,
        "contract_type": draft_request.get("contract_type", "unknown"),
        "template_id": template_id,
        "template_body": template_body,
        "parties": draft_request.get("parties") or [],
        "effective_date": draft_request.get("effective_date"),
        "expiration_date": draft_request.get("expiration_date"),
        "total_value_usd": draft_request.get("total_value_usd"),
        "payment_terms": draft_request.get("payment_terms"),
        "scope_summary": draft_request.get("scope_summary", ""),
        "key_terms_requested": draft_request.get("key_terms_requested") or [],
        "jurisdiction": draft_request.get("jurisdiction", "Ohio"),
        "notes": draft_request.get("notes", ""),
        "prior_contract_upload_id": draft_request.get("prior_contract_upload_id"),
        "context": {"contract_upload_id": upload_id},
    }
    return agent_input


# ---------------------------------------------------------------------------
# Core dispatch function
# ---------------------------------------------------------------------------
async def dispatch_one_draft(
    upload_id: str,
    contract_data: dict[str, Any],
    *,
    config: Config,
    queue_client: QueueClient,
) -> str | None:
    """Run the contract-drafter for one upload and submit to the approval queue.

    Returns the approval_item_id on success, None on failure.
    """
    agent_input = _build_draft_input(upload_id, contract_data)

    log.info(
        "contract_draft.running_agent",
        upload_id=upload_id,
        mode=agent_input.get("mode"),
    )

    agent = Agent("contract-drafter", config=config)
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
            "contract_draft.validation_warn",
            upload_id=upload_id,
            errors=(run.validation_errors or [])[:5],
        )

    approval_payload: dict[str, Any] = {
        "artifact": run.output,
        "contract_upload_id": upload_id,
        "context": {"contract_upload_id": upload_id},
    }

    # Contract drafts are mandatory human review (Lane 3)
    lane = 3
    required_approvers = ["owner", "partner"]

    submit_payload: dict[str, Any] = {
        "agent_id": "contract-drafter",
        "agent_version": run.agent_version,
        "workflow": "contract_draft.publish",
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
        "contract_draft.dispatched",
        upload_id=upload_id,
        approval_item_id=approval_item_id,
        lane=lane,
    )
    return approval_item_id


# ---------------------------------------------------------------------------
# Dispatcher daemon
# ---------------------------------------------------------------------------
class ContractDraftDispatcher:
    """Polling daemon that drafts contracts.

    Polls for contracts where:
    - status == 'drafting'
    - source == 'drafted'

    For each such contract, runs contract-drafter and submits a
    contract_draft.publish approval item (Lane 3 — mandatory human review).
    """

    def __init__(
        self,
        *,
        config: Config | None = None,
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
        state_file: Path | None = None,
        draft_requests_dir: Path | None = None,
    ) -> None:
        self.config = config or get_config()
        self.poll_interval_s = poll_interval_s
        self.state_file = state_file or _DEFAULT_STATE_FILE_PATH
        self.draft_requests_dir = draft_requests_dir or _DEFAULT_DRAFT_REQUESTS_DIR
        self._state = _load_state(self.state_file)
        self._stop_event = asyncio.Event()

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
        """Scan the draft_requests directory for priority markers."""
        if not self.draft_requests_dir.exists():
            return set()
        ids: set[str] = set()
        for f in self.draft_requests_dir.glob("*.json"):
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
        contracts = await _fetch_drafting_contracts(http_client, self.config)
        priority_ids = self._priority_upload_ids()

        upload_ids: list[str] = [c["upload_id"] for c in contracts]
        for uid in priority_ids:
            if uid not in upload_ids:
                upload_ids.append(uid)

        for upload_id in upload_ids:
            if self._is_dispatched(upload_id):
                _cleanup_priority_marker(self.draft_requests_dir, upload_id)
                continue

            err_entry = self._get_error_entry(upload_id)
            if err_entry and not _is_retryable(err_entry):
                log.debug(
                    "contract_draft.backoff",
                    upload_id=upload_id,
                    retry_after=err_entry.retry_after,
                )
                continue

            contract_data = await _fetch_contract(http_client, self.config, upload_id)
            if contract_data is None:
                continue

            # Guard: skip if already has a draft artifact (race condition).
            if contract_data.get("draft_artifact_id") is not None:
                log.info("contract_draft.already_drafted", upload_id=upload_id)
                self._record_success(upload_id, approval_item_id=None)
                _cleanup_priority_marker(self.draft_requests_dir, upload_id)
                continue

            # Guard: must be in drafting status and source=drafted
            if contract_data.get("status") != "drafting":
                log.debug(
                    "contract_draft.not_drafting",
                    upload_id=upload_id,
                    status=contract_data.get("status"),
                )
                continue

            if contract_data.get("source") != "drafted":
                log.debug(
                    "contract_draft.wrong_source",
                    upload_id=upload_id,
                    source=contract_data.get("source"),
                )
                continue

            try:
                approval_item_id = await dispatch_one_draft(
                    upload_id,
                    contract_data,
                    config=self.config,
                    queue_client=queue_client,
                )
                self._record_success(upload_id, approval_item_id)
                _cleanup_priority_marker(self.draft_requests_dir, upload_id)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "contract_draft.dispatch_failed",
                    upload_id=upload_id,
                    err=str(exc),
                )
                self._record_error(upload_id, str(exc))

    async def start(self) -> None:
        """Main loop. Runs until ``stop()`` is called or SIGTERM/SIGINT."""
        log.info(
            "contract_draft.dispatcher.start",
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
                    log.error("contract_draft.tick_error", err=str(exc))

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.poll_interval_s
                    )
                except asyncio.TimeoutError:
                    continue

        log.info(
            "contract_draft.dispatcher.stop",
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


def install_draft_signal_handlers(dispatcher: ContractDraftDispatcher) -> None:
    """Wire SIGTERM and SIGINT to a graceful stop."""

    def _handle(signum: int, _frame: Any) -> None:
        log.info("contract_draft.signal_received", signal=signum)
        dispatcher.stop()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


__all__ = [
    "ContractDraftDispatcher",
    "DraftDispatcherState",
    "dispatch_one_draft",
    "install_draft_signal_handlers",
    "_build_draft_input",
]
