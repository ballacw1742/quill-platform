"""Dispatcher — receives feeder events and routes them to the right agent.

Routing table:

    rfi.new              → rfi-triage (Lane 2 single approve)
    submittal.new        → submittal-triage + submittal-spec-validator (Lane 2)
    dfr.new              → dfr-synthesizer (Lane 1 auto, low risk; falls back to Lane 2)
    procurement.update   → procurement-watch (Lane 2 if slip; otherwise no-op)
    hyperscaler.inbound  → inbound-ingest classifier → fan-out

In dev/CI we don't actually call the LLM. Instead the dispatcher posts an
ApprovalCreate directly to the API (the same payload an agent would have
emitted). When ANTHROPIC_API_KEY is set, an opt-in path can be wired up
later — out of scope for Sprint 3.

Dispatcher writes a JSONL log to mock-data/_state/dispatch.log so the
Daily Brief pipeline can read yesterday's activity.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import structlog

from quill_mock_data.feeders import FeederEvent

log = structlog.get_logger(__name__)

STATE_DIR = Path(__file__).resolve().parent.parent / "_state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
DISPATCH_LOG = STATE_DIR / "dispatch.log"


def _api_url() -> str:
    return os.environ.get("QUILL_API_URL", "http://localhost:8000").rstrip("/")


def _agent_secret() -> str:
    return os.environ.get("AGENT_SHARED_SECRET", "dev-agent-secret-change-me")


# ---------------------------------------------------------------------------
# Per-event → ApprovalCreate payload builders
# ---------------------------------------------------------------------------
def _build_approval_for_rfi(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_id": "rfi-triage",
        "agent_version": "0.1.0",
        "workflow": "rfi.classify",
        "lane": 2,
        "priority": payload.get("priority", "normal"),
        "target_system": "procore",
        "api_call": f"POST /procore/projects/QPB1/rfis/{payload['rfi_id']}/classify",
        "payload": {
            "rfi_id": payload["rfi_id"],
            "category": payload["discipline"],
            "spec_section": payload["spec_section"],
            "building": payload["building"],
            "suggested_assignee": f"{payload['discipline']}-EOR",
        },
        "source_artifacts": [
            {"kind": "rfi", "ref": payload["rfi_id"], "excerpt": payload["body"][:280]}
        ],
        "citations": [
            {"source_type": "spec_section", "source_id": payload["spec_section"]},
            {"source_type": "drawing", "source_id": payload["drawing_id"]},
        ],
        "agent_confidence": 0.78,
        "agent_reasoning": (
            f"RFI references {payload['spec_section']} from {payload['subcontractor']}; "
            f"discipline={payload['discipline']} on {payload['building']}."
        ),
    }


def _build_approval_for_submittal(payload: dict[str, Any]) -> dict[str, Any]:
    is_non_conforming = payload["contents"].get("compliant") is False
    workflow = "submittal.review.first-pass"
    finding = "non_compliant" if is_non_conforming else "compliant"
    confidence = 0.74 if is_non_conforming else 0.88
    return {
        "agent_id": "submittal-spec-validator",
        "agent_version": "0.1.0",
        "workflow": workflow,
        "lane": 2 if is_non_conforming else 1,
        "priority": "high" if is_non_conforming else "normal",
        "target_system": "procore",
        "api_call": f"POST /procore/projects/QPB1/submittals/{payload['submittal_id']}/review",
        "payload": {
            "submittal_id": payload["submittal_id"],
            "finding": finding,
            "spec_section": payload["spec_section"],
            "delta": payload["contents"].get("deltas", []),
            "subcontractor": payload["subcontractor"],
            "building": payload["building"],
        },
        "source_artifacts": [{"kind": "submittal", "ref": payload["submittal_id"]}],
        "citations": [
            {"source_type": "spec_section", "source_id": payload["spec_section"]}
        ],
        "agent_confidence": confidence,
        "agent_reasoning": (
            f"{payload['package_type']} {payload['submittal_id']} vs spec "
            f"{payload['spec_section']}: {finding}."
        ),
    }


def _build_approval_for_dfr(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_id": "daily-brief",  # Sprint 2 fleet has dfr-synthesizer plumbed via daily-brief
        "agent_version": "0.1.0",
        "workflow": "dfr.synthesize",
        "lane": 1,
        "priority": "normal",
        "target_system": "p6",
        "api_call": f"POST /p6/projects/QPB1/progress/{payload['building']}/{payload['report_date']}",
        "payload": {
            "dfr_id": payload["dfr_id"],
            "building": payload["building"],
            "report_date": payload["report_date"],
            "headcount": payload["headcount"],
            "progress_proposals": [
                {
                    "activity_id": q["activity_id"],
                    "pct_complete": q["pct"],
                    "installed_qty": q["installed"],
                    "total_qty": q["total"],
                    "uom": q["uom"],
                }
                for q in payload["quantities"]
            ],
        },
        "source_artifacts": [
            {"kind": "dfr", "ref": payload["dfr_id"], "excerpt": payload["narrative"][:300]}
        ],
        "citations": [],
        "agent_confidence": 0.91,
        "agent_reasoning": (
            f"DFR rolled up to {len(payload['quantities'])} activity progress proposals "
            f"for {payload['building']} on {payload['report_date']}."
        ),
    }


def _build_approval_for_procurement(payload: dict[str, Any]) -> dict[str, Any] | None:
    # Only escalate if there's a slip or shipped/delivery_confirmed (low-risk auto)
    slip_weeks = payload.get("slip_weeks", 0)
    if slip_weeks == 0 and payload["kind"] not in ("shipped", "delivery_confirmed", "delay_notice"):
        return None
    is_critical = slip_weeks >= 3
    return {
        "agent_id": "procurement-watch",
        "agent_version": "0.1.0",
        "workflow": "po.long_lead.alert" if slip_weeks else "po.status.update",
        "lane": 3 if is_critical else (2 if slip_weeks else 1),
        "priority": "critical_path" if is_critical else ("high" if slip_weeks else "normal"),
        "target_system": "none",
        "api_call": None,
        "payload": {
            "po_id": payload["po_id"],
            "vendor": payload["vendor"],
            "item": payload["item"],
            "kind": payload["kind"],
            "slip_weeks": slip_weeks,
            "agreed_ship_date": payload["agreed_ship_date"],
            "revised_ship_date": payload.get("revised_ship_date"),
            "cp_activities": payload.get("cp_activity_refs", []),
        },
        "source_artifacts": [
            {"kind": "vendor_email", "ref": payload["po_id"], "excerpt": payload["email_body"][:300]}
        ],
        "citations": [
            {"source_type": "po_record", "source_id": payload["po_id"]}
        ],
        "agent_confidence": 0.83 if slip_weeks else 0.92,
        "agent_reasoning": (
            f"PO {payload['po_id']} ({payload['vendor']}) status={payload['kind']}; "
            f"slip_weeks={slip_weeks}"
            + (f"; impacts CP activities {payload.get('cp_activity_refs', [])}" if is_critical else "")
        ),
    }


def _build_approval_for_hyperscaler(payload: dict[str, Any]) -> dict[str, Any]:
    kind = payload["kind"]
    lane = 2
    priority = "normal"
    if kind in ("owner_directive", "milestone_update"):
        lane = 3
        priority = "high"
    if kind == "rfi_request":
        priority = "normal"

    return {
        "agent_id": "coordinator",
        "agent_version": "0.1.0",
        "workflow": "inbound.ingest",
        "lane": lane,
        "priority": priority,
        "target_system": "drive",
        "api_call": None,
        "payload": {
            "inbound_id": payload["inbound_id"],
            "classified_as": kind,
            "from_rep": payload["from_rep"],
            "spec_section": payload.get("spec_section"),
            "subject": payload["subject"],
        },
        "source_artifacts": [
            {"kind": "hyperscaler_inbound", "ref": payload["inbound_id"],
             "excerpt": payload["body"][:300]}
        ],
        "citations": [
            {"source_type": "owner_email", "source_id": payload["from_email"]}
        ],
        "agent_confidence": 0.80,
        "agent_reasoning": (
            f"Inbound from {payload['from_rep']} classified as {kind}; "
            f"routed for review."
        ),
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
class Dispatcher:
    """Dispatch FeederEvents to the API as ApprovalCreate POSTs.

    `dry_run=True` builds payloads but does not POST — useful for tests.
    """

    def __init__(self, *, dry_run: bool = False, http_timeout: float = 10.0) -> None:
        self.dry_run = dry_run
        self.http_timeout = http_timeout
        self._client: httpx.AsyncClient | None = None
        self.stats: dict[str, int] = {
            "rfi.new": 0, "submittal.new": 0, "dfr.new": 0,
            "procurement.update": 0, "hyperscaler.inbound": 0,
            "skipped": 0, "errors": 0, "submitted": 0,
        }

    async def __aenter__(self) -> Dispatcher:
        if not self.dry_run:
            self._client = httpx.AsyncClient(
                base_url=_api_url(), timeout=self.http_timeout
            )
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def build_payload(self, event: FeederEvent) -> dict[str, Any] | None:
        if event.kind == "rfi.new":
            return _build_approval_for_rfi(event.payload)
        if event.kind == "submittal.new":
            return _build_approval_for_submittal(event.payload)
        if event.kind == "dfr.new":
            return _build_approval_for_dfr(event.payload)
        if event.kind == "procurement.update":
            return _build_approval_for_procurement(event.payload)
        if event.kind == "hyperscaler.inbound":
            return _build_approval_for_hyperscaler(event.payload)
        log.warning("dispatcher.unknown_kind", kind=event.kind)
        return None

    async def dispatch(self, event: FeederEvent) -> dict[str, Any]:
        body = self.build_payload(event)
        if body is None:
            self.stats["skipped"] += 1
            self._log_dispatch(event, status="skipped", body=None, response=None)
            return {"status": "skipped", "kind": event.kind}

        self.stats[event.kind] = self.stats.get(event.kind, 0) + 1

        if self.dry_run or self._client is None:
            self.stats["submitted"] += 1
            self._log_dispatch(event, status="dry_run", body=body, response=None)
            return {"status": "dry_run", "kind": event.kind, "body": body}

        try:
            r = await self._client.post(
                "/v1/approvals",
                json=body,
                headers={
                    "X-Agent-Secret": _agent_secret(),
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as e:
            self.stats["errors"] += 1
            self._log_dispatch(event, status="http_error", body=body, response=str(e))
            log.error("dispatcher.http_error", error=str(e), kind=event.kind)
            return {"status": "error", "error": str(e)}

        if r.status_code >= 300:
            self.stats["errors"] += 1
            self._log_dispatch(event, status=f"http_{r.status_code}", body=body, response=r.text[:300])
            log.error("dispatcher.api_error", status_code=r.status_code, text=r.text[:300])
            return {"status": "error", "code": r.status_code, "body_returned": r.text[:300]}

        out = r.json()
        self.stats["submitted"] += 1
        self._log_dispatch(event, status="submitted", body=body, response={"approval_id": out.get("id")})
        return {"status": "submitted", "approval_id": out.get("id"), "lane": out.get("lane")}

    def _log_dispatch(self, event: FeederEvent, *, status: str,
                      body: dict[str, Any] | None,
                      response: Any) -> None:
        # Phase F.1: embed the original event payload so the
        # TriageDispatcher (runtime/runtime/triage_dispatcher.py) can pick
        # up the event with enough context to feed downstream agents.
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": event.kind,
            "source": event.source,
            "status": status,
            "summary": _summary_for(event),
            "approval_id": (response or {}).get("approval_id") if isinstance(response, dict) else None,
            "lane": (body or {}).get("lane"),
            "priority": (body or {}).get("priority"),
            "agent_id": (body or {}).get("agent_id"),
            # Full event payload for downstream chain consumption.
            "payload": event.payload,
            # Stable event_id for dedup across dispatcher restarts.
            "event_id": _event_id_for(event, status, response),
        }
        with DISPATCH_LOG.open("a") as f:
            f.write(json.dumps(rec) + "\n")


def _event_id_for(event: FeederEvent, status: str, response: Any) -> str:
    """Stable id for dedup. Prefer the API-assigned approval_id; otherwise
    composite of (kind, primary-ref, status)."""
    if isinstance(response, dict) and response.get("approval_id"):
        return str(response["approval_id"])
    p = event.payload
    primary_ref = (
        p.get("rfi_id")
        or p.get("submittal_id")
        or p.get("dfr_id")
        or p.get("po_id")
        or p.get("inbound_id")
        or ""
    )
    return f"{event.kind}:{primary_ref}:{status}"


def _summary_for(event: FeederEvent) -> str:
    p = event.payload
    if event.kind == "rfi.new":
        return f"{p['rfi_id']} {p['discipline']} on {p['building']} ({p.get('priority')})"
    if event.kind == "submittal.new":
        return f"{p['submittal_id']} {p['package_type']} {p['spec_section']}"
    if event.kind == "dfr.new":
        return f"{p['dfr_id']} headcount={p['headcount']}"
    if event.kind == "procurement.update":
        return f"{p['po_id']} {p['kind']} slip={p.get('slip_weeks',0)}wk"
    if event.kind == "hyperscaler.inbound":
        return f"{p['inbound_id']} {p['kind']} from {p['from_rep']}"
    return event.kind


async def dispatch_many(events: list[FeederEvent], *, dry_run: bool = False) -> list[dict[str, Any]]:
    async with Dispatcher(dry_run=dry_run) as d:
        return [await d.dispatch(e) for e in events]


def dispatch_many_sync(events: list[FeederEvent], *, dry_run: bool = False) -> list[dict[str, Any]]:
    return asyncio.run(dispatch_many(events, dry_run=dry_run))
