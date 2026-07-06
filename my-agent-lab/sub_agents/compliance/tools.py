"""Compliance tools — read checklists and deadlines from the Quill backend."""
from __future__ import annotations

from typing import Any

from google.adk.tools import FunctionTool

from tools.quill_api import as_items, quill_get


def list_checklists() -> list[dict[str, Any]]:
    """List compliance checklists with completion status.

    Returns a list of checklist objects. Use these to compute completion rates.
    On error, returns a single-element list containing an ``error`` key.
    """
    payload = quill_get("/v1/compliance/checklists")
    if isinstance(payload, dict) and payload.get("error"):
        return [payload]
    return as_items(payload)


def get_upcoming_deadlines() -> dict[str, Any]:
    """Get upcoming compliance/regulatory deadlines (obligations + contracts).

    Returns a dict describing items due soon. Flag anything past due or due
    within 7 days as high priority.
    """
    return quill_get("/v1/compliance/upcoming")


def get_compliance_summary() -> dict[str, Any]:
    """Get the portfolio compliance health summary."""
    return quill_get("/v1/compliance/summary")


list_checklists_tool = FunctionTool(func=list_checklists)
get_upcoming_deadlines_tool = FunctionTool(func=get_upcoming_deadlines)
get_compliance_summary_tool = FunctionTool(func=get_compliance_summary)

COMPLIANCE_TOOLS = [
    list_checklists_tool,
    get_upcoming_deadlines_tool,
    get_compliance_summary_tool,
]
