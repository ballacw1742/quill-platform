"""Quill tool suite v1 — read-only, X-Agent-Secret authenticated.

Same pattern as the spike's quill_finance_summary: GET the production Quill
API with the shared agent secret (Secret Manager), return compact JSON for
the model. All six tools are read-only; writes stay behind the /queue HITL
approval system per design doc §5 (out of A1 scope).

Endpoints (canonical shapes: api/app/routes/* — do not invent contracts):
  quill_finance_summary        GET /v1/finance/summary
  quill_pipeline_summary       GET /v1/deals?limit=500  (aggregated here —
                               the API has no /v1/pipeline/summary endpoint)
  quill_operations_summary     GET /v1/campuses?limit=200  (aggregated here)
  quill_customers_summary      GET /v1/customers/summary
  quill_intelligence_brief     GET /v1/intelligence/brief
  quill_list_pending_approvals GET /v1/approvals?status=pending
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

import httpx

from app.config import get_settings
from app.tools.base import Tool

log = logging.getLogger("agentcloud.tools.quill")


async def _quill_get(path: str, params: dict[str, Any] | None = None) -> dict | list | str:
    s = get_settings()
    if not s.QUILL_AGENT_SECRET:
        return {"error": "QUILL_AGENT_SECRET not configured"}
    try:
        async with httpx.AsyncClient(timeout=s.QUILL_TOOL_TIMEOUT_SECONDS) as client:
            r = await client.get(
                f"{s.QUILL_API_URL}{path}",
                params=params,
                headers={"X-Agent-Secret": s.QUILL_AGENT_SECRET},
            )
    except httpx.HTTPError as exc:
        log.warning("quill api request failed: %s %s", path, exc)
        return {"error": f"quill api request failed: {exc}"}
    if r.status_code != 200:
        return {"error": f"quill api {r.status_code}", "body": r.text[:500]}
    try:
        return r.json()
    except ValueError:
        return r.text[:2000]


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)


# --- handlers ---------------------------------------------------------------


async def _finance_summary(_args: dict[str, Any]) -> str:
    return _dumps(await _quill_get("/v1/finance/summary"))


async def _pipeline_summary(_args: dict[str, Any]) -> str:
    data = await _quill_get("/v1/deals", params={"limit": 500})
    if not isinstance(data, dict) or "items" not in data:
        return _dumps(data)
    by_stage: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "value_usd": 0.0})
    total_value = 0.0
    open_value = 0.0
    items = data.get("items", [])
    for deal in items:
        stage = str(deal.get("stage", "unknown"))
        value = float(deal.get("value_usd") or 0.0)
        by_stage[stage]["count"] += 1
        by_stage[stage]["value_usd"] += value
        total_value += value
        if stage not in ("won", "lost"):
            open_value += value
    return _dumps(
        {
            "total_deals": data.get("total", len(items)),
            "total_value_usd": total_value,
            "open_pipeline_value_usd": open_value,
            "by_stage": dict(by_stage),
        }
    )


async def _operations_summary(_args: dict[str, Any]) -> str:
    data = await _quill_get("/v1/campuses", params={"limit": 200})
    if not isinstance(data, dict) or "items" not in data:
        return _dumps(data)
    by_status: dict[str, int] = defaultdict(int)
    mw_capacity = 0.0
    mw_live = 0.0
    campuses = []
    for c in data.get("items", []):
        status = str(c.get("status", "unknown"))
        by_status[status] += 1
        mw_capacity += float(c.get("mw_capacity") or 0.0)
        mw_live += float(c.get("mw_live") or 0.0)
        campuses.append(
            {
                "name": c.get("name"),
                "status": status,
                "mw_capacity": c.get("mw_capacity"),
                "mw_live": c.get("mw_live"),
            }
        )
    return _dumps(
        {
            "total_campuses": data.get("total", len(campuses)),
            "by_status": dict(by_status),
            "mw_capacity_total": mw_capacity,
            "mw_live_total": mw_live,
            "campuses": campuses,
        }
    )


async def _customers_summary(_args: dict[str, Any]) -> str:
    return _dumps(await _quill_get("/v1/customers/summary"))


async def _intelligence_brief(_args: dict[str, Any]) -> str:
    return _dumps(await _quill_get("/v1/intelligence/brief"))


async def _list_pending_approvals(args: dict[str, Any]) -> str:
    limit = int(args.get("limit", 20))
    limit = max(1, min(limit, 100))
    data = await _quill_get("/v1/approvals", params={"status": "pending", "limit": limit})
    if not isinstance(data, dict) or "items" not in data:
        return _dumps(data)
    trimmed = [
        {
            "id": it.get("id"),
            "workflow": it.get("workflow"),
            "agent_id": it.get("agent_id"),
            "lane": it.get("lane"),
            "priority": it.get("priority"),
            "status": it.get("status"),
            "created_at": it.get("created_at"),
        }
        for it in data.get("items", [])
    ]
    return _dumps({"total": data.get("total", len(trimmed)), "items": trimmed})


# --- tool objects -------------------------------------------------------------

quill_finance_summary = Tool(
    name="quill_finance_summary",
    description=(
        "Live Quill portfolio financial summary (ARR, pipeline, capex, project "
        "budgets, AR aging) from the production Quill API. Read-only."
    ),
    handler=_finance_summary,
)

quill_pipeline_summary = Tool(
    name="quill_pipeline_summary",
    description=(
        "Live Quill sales pipeline summary: deal counts and USD value by stage "
        "(prospect/qualified/proposal/negotiating/won/lost), total and open "
        "pipeline value. Read-only."
    ),
    handler=_pipeline_summary,
)

quill_operations_summary = Tool(
    name="quill_operations_summary",
    description=(
        "Live Quill operations summary: data-center campuses by status, total "
        "and energized MW capacity. Read-only."
    ),
    handler=_operations_summary,
)

quill_customers_summary = Tool(
    name="quill_customers_summary",
    description=(
        "Live Quill customer portfolio summary: total customers, open tickets, "
        "critical-ticket flag, average health score, at-risk count. Read-only."
    ),
    handler=_customers_summary,
)

quill_intelligence_brief = Tool(
    name="quill_intelligence_brief",
    description=(
        "Structured Quill morning brief: incidents, revenue, construction, "
        "sites, customers, supply chain, and action items. Read-only."
    ),
    handler=_intelligence_brief,
)

quill_list_pending_approvals = Tool(
    name="quill_list_pending_approvals",
    description=(
        "List pending human-approval queue items in Quill (id, workflow, lane, "
        "priority, created_at). Read-only; approving/rejecting is human-only."
    ),
    handler=_list_pending_approvals,
    input_schema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max items to return (1-100, default 20).",
            }
        },
    },
)

QUILL_TOOLS = [
    quill_finance_summary,
    quill_pipeline_summary,
    quill_operations_summary,
    quill_customers_summary,
    quill_intelligence_brief,
    quill_list_pending_approvals,
]
