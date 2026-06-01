"""Schedule file parser tool — reads XER, MPP, P6 XML, and CSV schedule files."""
from __future__ import annotations

from typing import Any

from google.adk.tools import FunctionTool


def parse_schedule_file(file_ref: str, file_format: str) -> dict[str, Any]:
    """Parse a project schedule file (XER, MPP, P6 XML, or CSV) into structured data.

    TODO: wire to a real schedule parsing library:
      - XER/P6 XML: use xerparser (pip install xerparser) or xer-reader
      - MPP: use jpype + MPXJ (pip install mpxj) or a REST microservice
      - CSV: use pandas / csv stdlib

    Currently returns fixture/stub data so testing doesn't crash.

    Args:
        file_ref: Path or URI to the schedule file
            (e.g. "/data/schedules/project.xer" or "gs://bucket/project.mpp").
        file_format: One of "xer", "mpp", "p6xml", "csv".

    Returns:
        Dict with keys:
            'data_date' (str) — ISO date the schedule was published.
            'start_date' (str) — project start date (ISO).
            'finish_date' (str) — project forecast finish date (ISO).
            'activity_count' (int) — total number of activities.
            'milestone_count' (int) — total number of milestones.
            'wbs_tree' (list[dict]) — list of WBS nodes, each with:
                'wbs_id', 'name', 'parent_id' (str | None).
            'activities' (list[dict]) — list of activity records, each with:
                'activity_id', 'name', 'wbs_id', 'start_date', 'finish_date',
                'duration_days', 'total_float_days', 'percent_complete',
                'predecessors' (list of {predecessor_id, type, lag_days}),
                'is_critical' (bool), 'is_milestone' (bool).
            'critical_path_activities' (list[str]) — activity_ids on the CP.
            'parse_warnings' (list[dict]) — list of {location, message} warnings.
    """
    # TODO: implement real parsing. Example for XER:
    #   from xerparser import Xer
    #   with open(file_ref, encoding="utf-8-sig") as f:
    #       xer = Xer(f.read())
    #   return serialize_xer(xer)

    return {
        "data_date": "1970-01-01",
        "start_date": "1970-01-01",
        "finish_date": "1970-01-01",
        "activity_count": 0,
        "milestone_count": 0,
        "wbs_tree": [],
        "activities": [],
        "critical_path_activities": [],
        "parse_warnings": [
            {
                "location": file_ref,
                "message": (
                    f"[STUB] parse_schedule_file called with format={file_format!r}. "
                    "TODO: implement real schedule parsing."
                ),
            }
        ],
    }


parse_schedule_file_tool = FunctionTool(func=parse_schedule_file)
