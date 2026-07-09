"""Requests routes — unified project submission interface (Requests tab).

Endpoints:
  POST  /v1/requests        — submit a project request (text + optional files)
  GET   /v1/requests        — list request history for the current user
  GET   /v1/requests/{id}   — get a single request by ID
  PATCH /v1/requests/{id}   — update request status/response (agent service account)

Intent classification (keyword-based, MVP):
  - estimate  → Estimates module
  - schedule  → Schedules module
  - rfi       → RFI module
  - contract  → Contracts module
  - general   → general / TBD

Dispatch:
  After creating a request record, a marker file is written to
  ``_state/request_dispatch_requests/{request_id}.json``.  An external
  coordinator agent picks up the marker, calls the appropriate Quill agent,
  and calls PATCH /v1/requests/{id} (using X-Agent-Secret) to store the
  response and flip status to complete/failed.

Auth: Bearer JWT (same as all other routes) + X-Agent-Secret for PATCH.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Optional

import json
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models_requests import RequestRecord
from app.routes.modules import is_feature_enabled, is_module_enabled
from app.rate_limit import DISPATCH_LIMIT, GET_LIMIT, limiter
from app.security import get_current_user, require_agent_secret

_settings = get_settings()

# ADK agents service URL — all intents route here via POST /invoke
ADK_URL: str = os.environ.get("ADK_AGENTS_URL", _settings.INTERNAL_API_URL)

# Maps intent → the home-screen module that owns it (Modular Framework Phase 2,
# MODULAR_FRAMEWORK_DESIGN.md §3.3). If the owning module is DISABLED for the
# caller's workspace, the request is skipped instead of dispatched — the
# time/cost saver. Intents with no entry here are never gated (always run).
INTENT_TO_MODULE: dict[str, str] = {
    "estimate": "estimates",
    "schedule": "projects",
    "rfi": "projects",
    "contract": "contracts",
    "site_evaluation": "sites",
    "site_research": "sites",
    "site_scoring": "sites",
    "site_status": "sites",
    "facility_ops": "operations",
    "campus": "operations",
    "incident": "operations",
    "uptime": "operations",
    "pue": "operations",
    "sales": "sales",
    "pipeline": "sales",
    "customer_success": "customers",
    "supply_chain": "supply-chain",
    "equipment": "supply-chain",
    "vendor": "supply-chain",
    "procurement": "supply-chain",
    "lead_time": "supply-chain",
    "delivery": "supply-chain",
    "finance": "finance",
    "compliance": "compliance",
    "intelligence": "intelligence",
    # "general" intentionally omitted — the coordinator/general path is never
    # gated so a catch-all request always gets a response.
}

# Phase 1: intent → (module, sub-feature). When the specific sub-feature is
# disabled (but the module is on), the request is still skipped. Only intents
# that map to a discrete feature appear here; others are gated at module level.
INTENT_TO_FEATURE: dict[str, str] = {
    "rfi": "rfi",
    "schedule": "schedule",
    "site_evaluation": "evaluation",
    "site_research": "research",
    "site_scoring": "scoring",
    "incident": "incidents",
    "uptime": "uptime",
    "pue": "uptime",
    "procurement": "procurement",
    "vendor": "vendors",
    "equipment": "equipment",
}

# Maps intent → ADK agent name for POST /invoke
INTENT_TO_ADK_AGENT: dict[str, str] = {
    "estimate":        "quill_coordinator",
    "schedule":        "quill_schedule_monitor",
    "rfi":             "quill_rfi_triage",
    "contract":        "quill_change_order",
    "general":         "quill_coordinator",
    "site_evaluation": "datasite_site_evaluator",
    "site_research":   "datasite_site_researcher",
    "site_scoring":    "datasite_site_scorer",
    "site_status":     "datasite_site_status",
    # Sprint 1A — Facility Operations
    "facility_ops":    "quill_facility_ops",
    "campus":          "quill_facility_ops",
    "incident":        "quill_facility_ops",
    "uptime":          "quill_facility_ops",
    "pue":             "quill_facility_ops",
    # Sprint 1B — Sales & Pipeline
    "sales":           "quill_sales",
    "pipeline":        "quill_sales",
    # Sprint 2A — Customer Success
    "customer_success": "quill_customer_success",
    # Sprint 2B — Supply Chain
    "supply_chain":    "quill_supply_chain",
    "equipment":       "quill_supply_chain",
    "vendor":          "quill_supply_chain",
    "procurement":     "quill_supply_chain",
    "lead_time":       "quill_supply_chain",
    "delivery":        "quill_supply_chain",
    # Sprint 5.2 — Finance
    "finance":         "quill_finance",
    "invoice":         "quill_finance",
    "arr":             "quill_finance",
    "capex":           "quill_finance",
    "cash":            "quill_finance",
    "budget":          "quill_finance",
    "payment":         "quill_finance",
    "overdue":         "quill_finance",
    # Sprint 3B — Executive Intelligence
    "intelligence":    "quill_intelligence",
    "brief":           "quill_intelligence",
    "overview":        "quill_intelligence",
    "summary":         "quill_intelligence",
    "kpi":             "quill_intelligence",
    "dashboard":       "quill_intelligence",
    "executive":       "quill_intelligence",
    "briefing":        "quill_intelligence",
    # Sprint 4A — Compliance Register
    "compliance":      "quill_compliance",
    "regulatory":      "quill_compliance",
    "insurance":       "quill_compliance",
    "obligation":      "quill_compliance",
    "filing":          "quill_compliance",
    "soc2":            "quill_compliance",
    "fisma":           "quill_compliance",
}

log = logging.getLogger("quill.requests")

router = APIRouter(prefix="/v1/requests", tags=["requests"])


# ---------------------------------------------------------------------------
# Schemas (local — not in global schemas.py to keep the diff scoped)
# ---------------------------------------------------------------------------

class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    message: str
    intent: str
    status: str
    response: Optional[str] = None
    output_module: Optional[str] = None
    output_id: Optional[str] = None
    drive_url: Optional[str] = None
    filenames: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class RequestListResponse(BaseModel):
    items: list[RequestOut]
    total: int
    limit: int
    offset: int


class RequestSubmitResponse(BaseModel):
    request_id: str
    intent: str
    status: str
    message: str


class RequestUpdateIn(BaseModel):
    """Payload for PATCH /v1/requests/{request_id} (agent service account)."""

    status: str  # complete | failed
    response: Optional[str] = None
    output_module: Optional[str] = None  # estimates | schedules | rfi | contracts
    output_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Dispatch helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REQUEST_DISPATCH_DIR = _REPO_ROOT / "_state" / "request_dispatch_requests"


# ---------------------------------------------------------------------------
# DataSite inline handlers
# ---------------------------------------------------------------------------

import re as _re

_ADDRESS_PATTERN = _re.compile(
    r"""(?i)
    \b
    (\d{2,6})            # street number
    \s+
    ([A-Za-z0-9 .,']+?)  # street name (non-greedy)
    ,\s*
    ([A-Za-z ]+?)         # city (non-greedy)
    [,\s]+
    ([A-Z]{2})            # state abbreviation
    (?:[,\s]*(\d{5}(?:-\d{4})))?  # optional ZIP
    """,
    _re.VERBOSE,
)


def _parse_address(text: str) -> dict | None:
    """Try to extract a US address from natural language. Returns a dict or None."""
    m = _ADDRESS_PATTERN.search(text)
    if not m:
        return None
    number, street, city, state, zip_code = m.groups()
    return {
        "address": f"{number.strip()} {street.strip()}",
        "city": city.strip().rstrip(","),
        "state": state.upper(),
        "zip": zip_code.strip() if zip_code else "",
    }


def _parse_site_id(text: str) -> str | None:
    """Look for a site ID pattern in the message (UUID-like or short hash)."""
    m = _re.search(r"\b([0-9a-f]{8}(?:-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?|[0-9a-f]{6,12})\b", text, _re.I)
    return m.group(1) if m else None


def _parse_target_workload(text: str) -> str:
    """Infer target workload from message keywords."""
    t = text.lower()
    if "hyperscale" in t:
        return "hyperscale_compute"
    if any(w in t for w in ["ai", "hpc", "gpu", "ml"]):
        return "ai_hpc"
    if any(w in t for w in ["edge", "latency"]):
        return "edge_latency"
    if "colo" in t or "colocation" in t:
        return "colocation"
    return "ai_hpc"


async def _handle_datasite_inline(intent: str, message: str, user_id: str) -> str:
    """Legacy inline handler — kept for reference only. All DataSite intents
    now route through ADK via _dispatch_to_agent. This function is no longer
    called.
    """
    quill_sites_url = f"{ADK_URL}/v1/sites"

    if intent == "site_evaluation":
        parsed = _parse_address(message)
        if not parsed:
            return (
                "To evaluate a site, please provide the full address. "
                "Example: \'Evaluate 3990 E Broad Street, Columbus OH 43213 for hyperscale compute\'"
            )
        addr_label = f"{parsed['address']}, {parsed['city']}, {parsed['state']}"
        if parsed["zip"]:
            addr_label += f" {parsed['zip']}"
        try:
            payload = {
                "address": parsed["address"],
                "city": parsed["city"],
                "state": parsed["state"],
                "zip": parsed["zip"],
                "target_workload": _parse_target_workload(message),
                "lead_source": "request_chat",
            }
            async with httpx.AsyncClient(timeout=30) as client:
                create_resp = await client.post(quill_sites_url, json=payload)
                create_resp.raise_for_status()
                site_data = create_resp.json()
                site_id = site_data.get("site_id") or site_data.get("id", "unknown")
            # Kick off the evaluation pipeline
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    await client.post(f"{quill_sites_url}/{site_id}/run", json={})
            except Exception as run_exc:  # noqa: BLE001
                log.warning("datasite_inline.run_failed site_id=%s err=%s", site_id, run_exc)
                # Non-fatal — site was created; pipeline can be triggered manually
            return (
                f"Site evaluation started for **{addr_label}**. "
                f"Site ID: `{site_id}`. "
                f"Check the Sites tab to track progress."
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("datasite_inline.site_eval_failed err=%s", exc)
            return (
                f"I attempted to create a site evaluation for {addr_label} but the DataSite "
                f"service returned an error ({exc}). "
                f"Please try again or use the Sites tab to submit manually."
            )

    # For research / scoring / status — try to find a matching site first
    site_id_hint = _parse_site_id(message)
    sites_summary = ""
    matched_site: dict | None = None

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            list_resp = await client.get(quill_sites_url)
            list_resp.raise_for_status()
            sites_raw = list_resp.json()
            sites: list[dict] = (
                sites_raw.get("items", sites_raw)
                if isinstance(sites_raw, dict)
                else sites_raw
            )
            if isinstance(sites, list) and sites:
                # Try to match by site_id hint or address keywords in the message
                msg_lower = message.lower()
                for s in sites:
                    sid = str(s.get("site_id") or s.get("id") or "")
                    addr = str(s.get("address") or s.get("property", {}).get("address") or "").lower()
                    city = str(s.get("city") or s.get("property", {}).get("city") or "").lower()
                    if site_id_hint and site_id_hint in sid:
                        matched_site = s
                        break
                    if addr and addr in msg_lower:
                        matched_site = s
                        break
                    if city and city in msg_lower:
                        matched_site = matched_site or s  # prefer addr match; city is fallback
                # Build a brief summary of all sites
                lines = []
                for s in sites[:5]:  # cap at 5 to keep responses short
                    sid = str(s.get("site_id") or s.get("id") or "—")
                    addr = s.get("address") or s.get("property", {}).get("address") or "Unknown"
                    st = s.get("status") or "—"
                    verdict = (
                        s.get("recommendation", {}).get("verdict")
                        or s.get("verdict")
                        or ""
                    )
                    score = (
                        s.get("scores", {}).get("total_weighted")
                        or s.get("total_score")
                        or ""
                    )
                    line = f"- **{addr}** (ID: `{sid}`) — Status: {st}"
                    if verdict:
                        line += f" | Verdict: {verdict}"
                    if score:
                        line += f" | Score: {score}"
                    lines.append(line)
                sites_summary = "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        log.warning("datasite_inline.list_sites_failed err=%s", exc)
        sites_summary = "*(Could not retrieve site list — DataSite service may be unavailable.)*"

    if intent == "site_status":
        if matched_site:
            sid = str(matched_site.get("site_id") or matched_site.get("id") or "—")
            addr = matched_site.get("address") or matched_site.get("property", {}).get("address") or "Unknown"
            st = matched_site.get("status") or "unknown"
            verdict = matched_site.get("recommendation", {}).get("verdict") or matched_site.get("verdict") or "pending"
            score = (
                matched_site.get("scores", {}).get("total_weighted")
                or matched_site.get("total_score")
                or "not yet scored"
            )
            stage = matched_site.get("stage") or matched_site.get("pipeline_stage") or st
            return (
                f"**Site Status: {addr}**\n"
                f"- Site ID: `{sid}`\n"
                f"- Pipeline stage: {stage}\n"
                f"- Verdict: {verdict}\n"
                f"- Score: {score}\n\n"
                f"Open the Sites tab for the full scorecard and report."
            )
        if sites_summary:
            return (
                f"Here are your active site evaluations:\n\n{sites_summary}\n\n"
                f"To check a specific site, mention its address or site ID."
            )
        return (
            "No site evaluations found in your pipeline. "
            "Use the Site Evaluator agent or the Sites tab to submit a new site."
        )

    if intent == "site_research":
        if matched_site:
            sid = str(matched_site.get("site_id") or matched_site.get("id") or "—")
            addr = matched_site.get("address") or matched_site.get("property", {}).get("address") or "Unknown"
            research = matched_site.get("research", {})
            power = research.get("power", {}).get("notes", "Not yet researched.")[:300]
            fiber = research.get("fiber", {}).get("notes", "Not yet researched.")[:300]
            zoning = research.get("zoning", {}).get("notes", "Not yet researched.")[:300]
            incentives = research.get("incentives", {}).get("notes", "Not yet researched.")[:300]
            return (
                f"**Research Summary: {addr}** (ID: `{sid}`)\n\n"
                f"**Power:** {power}\n\n"
                f"**Fiber:** {fiber}\n\n"
                f"**Zoning:** {zoning}\n\n"
                f"**Incentives:** {incentives}\n\n"
                f"Open the Sites tab for the full research report."
            )
        return (
            "To research a site, mention the address or site ID in your message. "
            "Example: \'Research utility capacity for our Columbus site\' or \'What fiber providers are near site abc123?\'. "
            f"Your active sites:\n\n{sites_summary or 'None found.'}"
        )

    if intent == "site_scoring":
        if matched_site:
            sid = str(matched_site.get("site_id") or matched_site.get("id") or "—")
            addr = matched_site.get("address") or matched_site.get("property", {}).get("address") or "Unknown"
            scores = matched_site.get("scores", {})
            if not scores:
                return (
                    f"**{addr}** (ID: `{sid}`) hasn't been scored yet. "
                    f"The evaluation pipeline may still be running — check the Sites tab for current status."
                )
            score_lines = []
            for k, v in scores.items():
                if k != "total_weighted" and isinstance(v, (int, float)):
                    score_lines.append(f"- {k.replace('_', ' ').title()}: {v}")
            total = scores.get("total_weighted", "—")
            verdict = matched_site.get("recommendation", {}).get("verdict") or "pending"
            risks = matched_site.get("recommendation", {}).get("risks", [])
            strengths = matched_site.get("recommendation", {}).get("strengths", [])
            result_lines = [
                f"**Score Breakdown: {addr}** (ID: `{sid}`)\n",
                f"**Total Score:** {total} | **Verdict:** {verdict}\n",
            ]
            if score_lines:
                result_lines.append("**Category Scores:**\n" + "\n".join(score_lines))
            if strengths:
                result_lines.append("\n**Strengths:** " + ", ".join(str(s) for s in strengths[:3]))
            if risks:
                result_lines.append("**Risks:** " + ", ".join(str(r) for r in risks[:3]))
            result_lines.append("\nOpen the Sites tab for the full scorecard.")
            return "\n".join(result_lines)
        return (
            "To explain or compare scores, mention the site address or ID. "
            "Example: \'Why did the Columbus site score low on fiber?\' or \'Explain the power score for site abc123\'\n\n"
            f"Your active sites:\n\n{sites_summary or 'None found.'}"
        )

    # Fallback
    return "I couldn\'t determine what you need. Please try specifying the site address or ID."


# ---------------------------------------------------------------------------
# Retry policy for transient ADK failures (Sprint 5.3)
# ---------------------------------------------------------------------------
_RETRY_MAX_ATTEMPTS = 3
_RETRY_BACKOFFS = [1, 2, 4]  # seconds — exponential backoff between attempts
_RETRYABLE_STATUS = {502, 503, 504}          # transient gateway/server errors
_NON_RETRYABLE_STATUS = {400, 401, 403, 404, 422}  # client errors — retry won't help


class _AgentUnavailable(Exception):
    """Raised when all retry attempts to reach an ADK agent are exhausted."""


async def _call_adk_with_retry(
    endpoint: str,
    payload: dict,
    agent_id: str,
    request_id: str,
) -> httpx.Response:
    """POST to the ADK agent with exponential backoff on transient failures.

    Retries on connection errors (httpx transport errors, incl. timeouts) and
    502/503/504 responses. Does NOT retry 400/401/403/404/422 — those are
    client errors that won't change on retry, so the response is returned to
    the caller as-is. After ``_RETRY_MAX_ATTEMPTS`` transient failures, raises
    :class:`_AgentUnavailable`.

    Each retry logs: attempt number, agent_id, and error type (Sprint 5.3).
    """
    last_error_type = "unknown"
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(endpoint, json=payload)
            if resp.status_code in _RETRYABLE_STATUS:
                last_error_type = f"http_{resp.status_code}"
                log.warning(
                    "dispatch.retry attempt=%d/%d agent_id=%s error_type=%s request_id=%s",
                    attempt, _RETRY_MAX_ATTEMPTS, agent_id, last_error_type, request_id,
                )
                if attempt < _RETRY_MAX_ATTEMPTS:
                    await asyncio.sleep(_RETRY_BACKOFFS[attempt - 1])
                    continue
                raise _AgentUnavailable(last_error_type)
            # Success (<400) or a non-retryable error (e.g. 400/422): return it
            # so the caller can surface the agent's own status/body.
            return resp
        except httpx.TransportError as exc:
            # Connection errors, timeouts, read/write/network errors — transient.
            last_error_type = type(exc).__name__
            log.warning(
                "dispatch.retry attempt=%d/%d agent_id=%s error_type=%s request_id=%s",
                attempt, _RETRY_MAX_ATTEMPTS, agent_id, last_error_type, request_id,
            )
            if attempt < _RETRY_MAX_ATTEMPTS:
                await asyncio.sleep(_RETRY_BACKOFFS[attempt - 1])
                continue
            raise _AgentUnavailable(last_error_type) from exc
    # Defensive — the loop always returns or raises above.
    raise _AgentUnavailable(last_error_type)


async def _dispatch_to_agent(
    request_id: str,
    intent: str,
    message: str,
    filenames: list[str],
    drive_url: str | None,
    user_id: str,
) -> None:
    """Async HTTP dispatcher — routes all intents through ADK /invoke.

    All intents (PMO and DataSite) go to the ADK agents service via
    POST {ADK_URL}/invoke with {agent, message, session_id}.

    On success: stores the response in the DB and marks the request complete.
    On failure: marks the request as failed.
    Fire-and-forget: never raises — all exceptions are caught.
    """
    from app.db import SessionLocal as async_session_maker  # noqa: N812
    from app.models import AgentRegistration  # noqa: N812

    # Look up which ADK agent handles this intent
    agent_name = INTENT_TO_ADK_AGENT.get(intent, INTENT_TO_ADK_AGENT["general"])
    adk_endpoint = f"{ADK_URL}/invoke"

    adk_payload = {
        "agent": agent_name,
        "message": message,
        "session_id": request_id,
    }

    new_status = "failed"
    response_text: str | None = None

    log.info(
        "dispatch.adk request_id=%s intent=%s agent=%s",
        request_id, intent, agent_name,
    )

    try:
        resp = await _call_adk_with_retry(
            adk_endpoint, adk_payload, agent_name, request_id
        )
        if resp.status_code < 400:
            new_status = "complete"
            try:
                body = resp.json()
                response_text = body.get("response", "") if isinstance(body, dict) else str(body)
            except Exception:
                response_text = resp.text[:2000]
        else:
            # Non-retryable client error surfaced from the agent (e.g. 400/422).
            response_text = f"ADK agent returned {resp.status_code}: {resp.text[:500]}"
            new_status = "failed"
    except _AgentUnavailable as exc:
        # All retries exhausted on transient failures. The canonical failure
        # message + HTTP 503 semantics live in _dispatch_to_agent's contract;
        # since dispatch is a fire-and-forget background task, the 503 is
        # recorded on the request row rather than returned to the (already
        # answered) POST /v1/requests caller.
        log.warning(
            "dispatch.exhausted request_id=%s agent=%s attempts=%d last_error=%s http_status=503",
            request_id, agent_name, _RETRY_MAX_ATTEMPTS, exc,
        )
        response_text = "Agent unavailable after 3 attempts. Try again later."
        new_status = "failed"
    except Exception as exc:  # noqa: BLE001
        log.exception("dispatch.unexpected_error request_id=%s", request_id)
        response_text = f"Unexpected dispatch error: {exc}"
        new_status = "failed"

    # Determine output_module for DataSite intents
    output_module: str | None = None
    if intent in ("site_evaluation", "site_research", "site_scoring", "site_status"):
        output_module = "sites"

    # Update the DB record (fire-and-forget — never blocks or raises)
    try:
        async with async_session_maker() as session:
            record = await session.get(RequestRecord, request_id)
            if record is not None:
                record.status = new_status
                record.response = response_text
                if output_module:
                    record.output_module = output_module
                record.updated_at = _utcnow()
                await session.commit()
                log.info(
                    "dispatch.complete request_id=%s intent=%s agent=%s status=%s",
                    request_id, intent, agent_name, new_status,
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("dispatch.db_update_failed request_id=%s err=%s", request_id, exc)

    # Fire-and-forget: update agent usage stats (never blocks or raises)
    asyncio.create_task(
        _update_agent_stats(agent_name, new_status)
    )


async def _update_agent_stats(agent_id: str, dispatch_status: str) -> None:
    """Update AgentRegistration usage counters. Fire-and-forget — never raises."""
    from app.db import SessionLocal as async_session_maker  # noqa: N812
    from app.models import AgentRegistration
    try:
        async with async_session_maker() as session:
            agent = await session.get(AgentRegistration, agent_id)
            if agent is not None:
                agent.requests_total = (agent.requests_total or 0) + 1
                if dispatch_status == "complete":
                    agent.requests_success = (agent.requests_success or 0) + 1
                else:
                    agent.requests_failed = (agent.requests_failed or 0) + 1
                agent.last_invoked_at = _utcnow()
                await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.debug("agent_stats.update_failed agent_id=%s err=%s", agent_id, exc)


def _write_dispatch_marker(
    request_id: str,
    intent: str,
    message: str,
    filenames: list[str],
    drive_url: str | None,
    user_id: str,
) -> None:
    """Write a JSON marker file for the external coordinator to pick up.

    Non-fatal: if the write fails the request is still accepted — the external
    coordinator can also poll ``project_requests`` for records stuck in
    ``processing`` status.
    """
    try:
        _REQUEST_DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
        marker_path = _REQUEST_DISPATCH_DIR / f"{request_id}.json"
        marker_path.write_text(
            json.dumps(
                {
                    "request_id": request_id,
                    "intent": intent,
                    "message": message,
                    "filenames": filenames,
                    "drive_url": drive_url,
                    "user_id": user_id,
                    "requested_at": _utcnow().isoformat(),
                }
            ),
            encoding="utf-8",
        )
        log.info("dispatch marker written request_id=%s intent=%s", request_id, intent)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "dispatch_marker.write_failed request_id=%s err=%s", request_id, exc
        )
        # Non-fatal — coordinator can poll project_requests for stuck records.


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

def classify_intent(message: str, filenames: list[str]) -> str:
    """Keyword-based intent classification. Returns one of:
    estimate | schedule | rfi | contract |
    site_evaluation | site_research | site_scoring | site_status | general
    """
    text = (message + " " + " ".join(filenames)).lower()

    # site_status — check early to catch "status of" before site_evaluation
    if any(w in text for w in ["status of", "site status", "where is", "pipeline status", "what stage"]):
        return "site_status"

    # site_scoring — explain / compare scores
    if any(w in text for w in ["why did", "explain the score", "re-score", "compare sites", "scorecard"]):
        return "site_scoring"
    if any(w in text for w in ["score", "scoring"]) and "site" in text:
        return "site_scoring"

    # site_research — utility, fiber, permitting, zoning, incentives in site context
    if any(w in text for w in ["research this site", "utility", "fiber", "permitting", "zoning", "incentives", "market conditions"]) and "site" in text:
        return "site_research"
    if "research" in text and any(w in text for w in ["site", "parcel", "data center", "location"]):
        return "site_research"

    # site_evaluation — submit a new site
    if any(w in text for w in ["evaluate site", "new site", "site evaluation", "go/no-go", "data center site", "site submission", "submit a site", "submit site", "site evaluator"]):
        return "site_evaluation"
    if "site" in text and any(w in text for w in ["evaluate", "feasibility", "data center potential", "hpc", "hyperscale", "colocation"]):
        return "site_evaluation"

    # facility_ops — campus / PUE / uptime / incident keywords (check before general)
    if any(w in text for w in ["campus", "pue", "power usage effectiveness", "uptime", "downtime", "facility ops", "facility operations", "data center campus", "live campus"]):
        return "facility_ops"
    if "incident" in text and any(w in text for w in ["campus", "data center", "p1", "p2", "p3", "p4", "outage", "degradation"]):
        return "incident"

    if any(w in text for w in ["estimate", "cost", "budget", "price", "bid", "scope", "takeoff", "quantity"]):
        return "estimate"
    if any(w in text for w in ["schedule", "timeline", "gantt", "critical path", "milestone", "sequenc", "duration"]):
        return "schedule"
    if any(w in text for w in ["rfi", "request for information", "clarification", "question", "submittal", "inquiry"]):
        return "rfi"
    if any(w in text for w in ["contract", "agreement", "subcontract", "clause", "terms", "conditions", "liability"]):
        return "contract"
    # Sprint 5.2 — Finance (invoice / ARR / cash / capex / overdue — finance-specific terms)
    if any(w in text for w in ["invoice", "capex", "cash position", "cash flow", "accounts receivable", "overdue", "arr", "annual recurring revenue", "budget vs actual", "budget variance", "budget vs. actual"]):
        return "finance"
    if "finance" in text or "financial" in text:
        return "finance"
    # Sprint 2A — Customer Success (check before pipeline/sales to catch customer-specific keywords)
    if any(w in text for w in ["support", "ticket", "health score", "churn", "customer success", "customer health", "at-risk customer", "account health", "open ticket", "p1 ticket", "p2 ticket"]):
        return "customer_success"
    if "customer" in text and any(w in text for w in ["health", "churn", "success", "support", "ticket", "at risk"]):
        return "customer_success"
    # Sprint 1B — Sales & Pipeline
    if any(w in text for w in ["customer", "deal", "pipeline", "prospect", "sales", "contract value", "arr", "annual recurring", "workload type", "mw required", "advance deal", "close deal", "qualified lead", "proposal sent", "win rate"]):
        return "sales"
    # Sprint 2B — Supply Chain
    if any(w in text for w in ["supply chain", "equipment", "vendor", "procurement", "lead time", "lead-time", "delivery", "generator", "switchgear", "ups system", "cooling unit", "at risk equipment", "at-risk equipment", "long lead", "long-lead"]):
        return "supply_chain"
    # Sprint 4A — Compliance Register (check before intelligence, specific terms)
    if any(w in text for w in ["compliance", "regulatory", "regulation", "obligation", "filing", "soc 2", "soc2", "iso 27001", "iso27001", "fisma", "nist", "ferc", "nerc", "epa", "gdpr", "ccpa", "insurance policy", "insurance renewal", "expiring insurance", "overdue obligation", "compliance checklist", "compliance register"]):
        return "compliance"
    # Sprint 3B — Executive Intelligence (check last, broad terms)
    if any(w in text for w in ["intelligence", "dashboard", "kpi", "brief", "morning brief", "scorecard", "how is the company", "company overview", "portfolio overview", "portfolio summary", "overall status"]):
        return "intelligence"
    if "overview" in text or "summary" in text:
        if any(w in text for w in ["company", "portfolio", "all modules", "all divisions", "across", "executive"]):
            return "intelligence"
    return "general"


def _intent_label(intent: str) -> str:
    labels = {
        "estimate": "Estimator",
        "schedule": "Scheduler",
        "rfi": "RFI Agent",
        "contract": "Contract Reviewer",
        "general": "Coordinator",
        "site_evaluation": "Site Evaluator",
        "site_research": "Site Researcher",
        "site_scoring": "Site Scorer",
        "site_status": "Site Status",
        "facility_ops": "Facility Ops Agent",
        "campus": "Facility Ops Agent",
        "incident": "Facility Ops Agent",
        "uptime": "Facility Ops Agent",
        "pue": "Facility Ops Agent",
        "sales": "Sales Agent",
        "pipeline": "Sales Agent",
        "customer_success": "Customer Success Agent",
        # Sprint 5.2 — Finance
        "finance": "Finance Agent",
        "invoice": "Finance Agent",
        "arr": "Finance Agent",
        "capex": "Finance Agent",
        "cash": "Finance Agent",
        "budget": "Finance Agent",
        "payment": "Finance Agent",
        "overdue": "Finance Agent",
        # Sprint 2B — Supply Chain
        "supply_chain": "Supply Chain Agent",
        "equipment": "Supply Chain Agent",
        "vendor": "Supply Chain Agent",
        "procurement": "Supply Chain Agent",
        "lead_time": "Supply Chain Agent",
        "delivery": "Supply Chain Agent",
        # Sprint 3B — Executive Intelligence
        "intelligence": "Intelligence Agent",
        "brief": "Intelligence Agent",
        "overview": "Intelligence Agent",
        "summary": "Intelligence Agent",
        "kpi": "Intelligence Agent",
        "dashboard": "Intelligence Agent",
        "executive": "Intelligence Agent",
        "briefing": "Intelligence Agent",
        # Sprint 4A — Compliance Register
        "compliance": "Compliance Agent",
        "regulatory": "Compliance Agent",
        "insurance": "Compliance Agent",
        "obligation": "Compliance Agent",
        "filing": "Compliance Agent",
        "soc2": "Compliance Agent",
        "fisma": "Compliance Agent",
    }
    return labels.get(intent, "Agent")


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# POST /v1/requests
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=RequestSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a project request",
)
@limiter.limit(DISPATCH_LIMIT)  # Sprint 5.3 — agent dispatch: 20/min per IP
async def submit_request(
    request: Request,
    message: str = Form(..., description="Describe your request"),
    files: list[UploadFile] = File(default=[]),
    drive_url: str = Form(default="", description="Optional Google Drive link"),
    intent_override: Optional[str] = Form(
        default=None,
        alias="intent",
        description="Optional intent override; skips auto-classification when provided.",
    ),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> RequestSubmitResponse:
    """
    Submit a project request. The system classifies intent and routes to the
    appropriate agent. Results appear in the relevant module.

    Intent routing:
    - estimate  → co_estimator agent → Estimates module
    - schedule  → schedule_reader agent → Schedules module
    - rfi       → rfi_triage + rfi_drafter → RFI module
    - contract  → contract_reviewer → Contracts module
    - general   → coordinator agent

    If ``intent`` is provided in the form payload and matches a known value,
    it overrides keyword-based auto-classification.
    """
    _VALID_INTENTS = {
        "estimate", "schedule", "rfi", "contract", "general",
        "site_evaluation", "site_research", "site_scoring", "site_status",
        # Sprint 5.2 — specialist data agents (allow explicit intent override)
        "facility_ops", "sales", "customer_success", "finance",
        "intelligence", "compliance", "supply_chain",
    }
    file_names = [f.filename or "" for f in files if f.filename]
    if intent_override and intent_override in _VALID_INTENTS:
        intent = intent_override
    else:
        intent = classify_intent(message, file_names)
    filenames_str = ",".join(file_names) if file_names else None

    # ── Modular Framework Phase 2 gate (MODULAR_FRAMEWORK_DESIGN.md §3.3) ──
    # If the module that owns this intent is DISABLED for the caller's personal
    # workspace, skip the agent dispatch entirely — record it as "skipped" and
    # return immediately (the time/cost saver). FAIL-OPEN: is_module_enabled
    # returns True on any ambiguity, so we never silently drop work.
    owning_module = INTENT_TO_MODULE.get(intent)
    owning_feature = INTENT_TO_FEATURE.get(intent)
    module_skipped = False
    if owning_module is not None:
        try:
            ws = f"personal:{user.id}"
            if owning_feature is not None:
                # Feature-level gate implies the module gate (feature off OR
                # whole module off both skip).
                module_skipped = not await is_feature_enabled(
                    db, ws, owning_module, owning_feature
                )
            else:
                module_skipped = not await is_module_enabled(db, ws, owning_module)
        except Exception:  # noqa: BLE001 — fail-open, never block on config error
            log.warning("module_gate.check_failed intent=%s module=%s — running anyway",
                        intent, owning_module)
            module_skipped = False

    record = RequestRecord(
        user_id=str(user.id),
        message=message,
        intent=intent,
        status="skipped" if module_skipped else "processing",
        drive_url=drive_url or None,
        filenames=filenames_str,
    )
    if module_skipped:
        record.response = (
            f"The {_intent_label(intent)} module is turned off for your workspace, "
            f"so this request was skipped. Enable it in Settings › Modules to process "
            f"requests like this."
        )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    if module_skipped:
        log.info("request skipped (module disabled) user=%s intent=%s module=%s id=%s",
                 user.id, intent, owning_module, record.id)
        return RequestSubmitResponse(
            request_id=record.id,
            intent=intent,
            status="skipped",
            message=f"The {_intent_label(intent)} module is off — request skipped.",
        )

    log.info(
        "request submitted user=%s intent=%s id=%s files=%d",
        user.id,
        intent,
        record.id,
        len(file_names),
    )

    # Dispatch to agent via async HTTP (with marker-file fallback for queued state).
    background_tasks.add_task(
        _dispatch_to_agent,
        request_id=record.id,
        intent=intent,
        message=message,
        filenames=file_names,
        drive_url=drive_url or None,
        user_id=str(user.id),
    )

    agent_label = _intent_label(intent)
    return RequestSubmitResponse(
        request_id=record.id,
        intent=intent,
        status="processing",
        message=f"Routing to {agent_label}…",
    )


# ---------------------------------------------------------------------------
# PATCH /v1/requests/{request_id} — agent service account callback
# ---------------------------------------------------------------------------


@router.patch(
    "/{request_id}",
    response_model=RequestOut,
    summary="Update request status/response (agent service account only)",
)
async def update_request(
    request_id: str,
    body: RequestUpdateIn,
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(require_agent_secret),
) -> RequestOut:
    """Called by the external coordinator agent after processing a request.

    Accepts only status values ``complete`` or ``failed``.
    Authenticated via X-Agent-Secret header.
    """
    record = await db.get(RequestRecord, request_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "request not found")

    allowed_statuses = {"complete", "failed"}
    if body.status not in allowed_statuses:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"status must be one of {sorted(allowed_statuses)}",
        )

    record.status = body.status
    record.updated_at = _utcnow()
    if body.response is not None:
        record.response = body.response
    if body.output_module is not None:
        record.output_module = body.output_module
    if body.output_id is not None:
        record.output_id = body.output_id

    await db.commit()
    await db.refresh(record)

    log.info(
        "request updated id=%s status=%s output_module=%s",
        request_id,
        body.status,
        body.output_module,
    )
    return RequestOut.model_validate(record)


# ---------------------------------------------------------------------------
# GET /v1/requests
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=RequestListResponse,
    summary="List project request history for the current user",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def list_requests(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> RequestListResponse:
    from sqlalchemy import func

    count_result = await db.execute(
        select(func.count()).select_from(RequestRecord).where(
            RequestRecord.user_id == str(user.id)
        )
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(RequestRecord)
        .where(RequestRecord.user_id == str(user.id))
        .order_by(RequestRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    records = result.scalars().all()

    return RequestListResponse(
        items=[RequestOut.model_validate(r) for r in records],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /v1/requests/{request_id}
# ---------------------------------------------------------------------------

@router.get(
    "/{request_id}",
    response_model=RequestOut,
    summary="Get a single project request",
)
@limiter.limit(GET_LIMIT)  # Sprint 5.3 — list/query: 120/min per IP
async def get_request(
    request: Request,
    request_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> RequestOut:
    record = await db.get(RequestRecord, request_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "request not found")
    if record.user_id != str(user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your request")
    return RequestOut.model_validate(record)
