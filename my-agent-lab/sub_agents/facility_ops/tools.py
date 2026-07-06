"""Facility Operations tools — read live campus data from the Quill backend."""
from __future__ import annotations

from typing import Any

from google.adk.tools import FunctionTool

from tools.quill_api import as_items, quill_get


def list_campuses() -> list[dict[str, Any]]:
    """List all data-center campuses with their status and headline metrics.

    Returns a list of campus objects (id, name, status, region, PUE, uptime,
    power draw, etc.). Use the campus ``id`` from here for incident/metric
    lookups. On error, returns a single-element list containing an ``error`` key.
    """
    payload = quill_get("/v1/campuses")
    if isinstance(payload, dict) and payload.get("error"):
        return [payload]
    return as_items(payload)


def get_campus_incidents(campus_id: str) -> list[dict[str, Any]]:
    """Get incidents for a single campus.

    Args:
        campus_id: The campus ``id`` returned by ``list_campuses``.

    Returns a list of incident objects (severity like P1/P2/P3/P4, title,
    status, opened_at). Surface any OPEN P1 or P2 incidents immediately.
    """
    payload = quill_get(f"/v1/campuses/{campus_id}/incidents")
    if isinstance(payload, dict) and payload.get("error"):
        return [payload]
    return as_items(payload)


def get_campus_metrics(campus_id: str) -> dict[str, Any]:
    """Get the metric history for a single campus (PUE, uptime, power over time).

    Args:
        campus_id: The campus ``id`` returned by ``list_campuses``.
    """
    return quill_get(f"/v1/campuses/{campus_id}/metrics")


list_campuses_tool = FunctionTool(func=list_campuses)
get_campus_incidents_tool = FunctionTool(func=get_campus_incidents)
get_campus_metrics_tool = FunctionTool(func=get_campus_metrics)

FACILITY_OPS_TOOLS = [list_campuses_tool, get_campus_incidents_tool, get_campus_metrics_tool]
