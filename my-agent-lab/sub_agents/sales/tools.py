"""Sales & Pipeline tools — read deals and accounts from the Quill backend."""
from __future__ import annotations

from typing import Any

from google.adk.tools import FunctionTool

from tools.quill_api import as_items, quill_get


def list_deals() -> list[dict[str, Any]]:
    """List all deals with stage, value, owner, and last-activity timestamp.

    Returns a list of deal objects. Use these to summarize pipeline by stage,
    total value, and win rate, and to detect stalled deals (no activity in
    >14 days). On error, returns a single-element list containing an ``error`` key.
    """
    payload = quill_get("/v1/deals")
    if isinstance(payload, dict) and payload.get("error"):
        return [payload]
    return as_items(payload)


def list_accounts() -> list[dict[str, Any]]:
    """List all accounts (prospects and customers) with basic firmographics."""
    payload = quill_get("/v1/accounts")
    if isinstance(payload, dict) and payload.get("error"):
        return [payload]
    return as_items(payload)


def get_pipeline_summary() -> dict[str, Any]:
    """Get the pre-aggregated pipeline summary (value by stage, counts, win rate)."""
    return quill_get("/v1/pipeline/summary")


def get_deal_activities(deal_id: str) -> list[dict[str, Any]]:
    """Get the activity history for one deal.

    Args:
        deal_id: The deal ``id`` returned by ``list_deals``.
    """
    payload = quill_get(f"/v1/deals/{deal_id}/activities")
    if isinstance(payload, dict) and payload.get("error"):
        return [payload]
    return as_items(payload)


list_deals_tool = FunctionTool(func=list_deals)
list_accounts_tool = FunctionTool(func=list_accounts)
get_pipeline_summary_tool = FunctionTool(func=get_pipeline_summary)
get_deal_activities_tool = FunctionTool(func=get_deal_activities)

SALES_TOOLS = [
    list_deals_tool,
    list_accounts_tool,
    get_pipeline_summary_tool,
    get_deal_activities_tool,
]
