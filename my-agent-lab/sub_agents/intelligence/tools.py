"""Executive Intelligence tools — cross-module rollups from the Quill backend.

This agent reads summary endpoints across Operations, Sales, Finance, and
Customer Success to build an executive briefing.
"""
from __future__ import annotations

from typing import Any

from google.adk.tools import FunctionTool

from tools.quill_api import as_items, quill_get


def get_kpis() -> dict[str, Any]:
    """Get the company-wide KPI snapshot (cross-module rollup)."""
    return quill_get("/v1/intelligence/kpis")


def get_exceptions() -> dict[str, Any]:
    """Get the cross-module exception feed (risks/flags across all modules)."""
    return quill_get("/v1/intelligence/exceptions")


def get_finance_summary() -> dict[str, Any]:
    """Get the finance summary (ARR, cash, capex, overdue invoices headline)."""
    return quill_get("/v1/finance/summary")


def list_campuses() -> list[dict[str, Any]]:
    """List campuses (Operations) — used to surface active P1/P2 incidents."""
    payload = quill_get("/v1/campuses")
    if isinstance(payload, dict) and payload.get("error"):
        return [payload]
    return as_items(payload)


def get_pipeline_summary() -> dict[str, Any]:
    """Get the sales pipeline summary (value by stage, win rate)."""
    return quill_get("/v1/pipeline/summary")


def list_customers() -> list[dict[str, Any]]:
    """List customers (Customer Success) — used to surface at-risk accounts."""
    payload = quill_get("/v1/customers")
    if isinstance(payload, dict) and payload.get("error"):
        return [payload]
    return as_items(payload)


get_kpis_tool = FunctionTool(func=get_kpis)
get_exceptions_tool = FunctionTool(func=get_exceptions)
get_finance_summary_tool = FunctionTool(func=get_finance_summary)
list_campuses_tool = FunctionTool(func=list_campuses)
get_pipeline_summary_tool = FunctionTool(func=get_pipeline_summary)
list_customers_tool = FunctionTool(func=list_customers)

INTELLIGENCE_TOOLS = [
    get_kpis_tool,
    get_exceptions_tool,
    get_finance_summary_tool,
    list_campuses_tool,
    get_pipeline_summary_tool,
    list_customers_tool,
]
