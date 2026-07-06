"""Finance tools — read financial summary and invoices from the Quill backend."""
from __future__ import annotations

from typing import Any

from google.adk.tools import FunctionTool

from tools.quill_api import as_items, quill_get


def get_finance_summary() -> dict[str, Any]:
    """Get the finance summary: ARR, cash position, capex, and budget headlines.

    Returns a dict. On error, returns a dict with an ``error`` key.
    """
    return quill_get("/v1/finance/summary")


def list_invoices() -> list[dict[str, Any]]:
    """List invoices with status, amount, and due date.

    Returns a list of invoice objects. Surface any OVERDUE invoices with their
    amounts. On error, returns a single-element list containing an ``error`` key.
    """
    payload = quill_get("/v1/finance/invoices")
    if isinstance(payload, dict) and payload.get("error"):
        return [payload]
    return as_items(payload)


def get_budget_variance() -> dict[str, Any]:
    """Get budget lines (budget vs actual) for variance analysis."""
    return quill_get("/v1/finance/budget-lines")


get_finance_summary_tool = FunctionTool(func=get_finance_summary)
list_invoices_tool = FunctionTool(func=list_invoices)
get_budget_variance_tool = FunctionTool(func=get_budget_variance)

FINANCE_TOOLS = [get_finance_summary_tool, list_invoices_tool, get_budget_variance_tool]
