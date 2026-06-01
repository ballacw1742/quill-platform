"""Output schema for the schedule_reader (Schedule File Parser) agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WbsNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wbs_id: str = Field(..., description="WBS identifier (e.g. '1.2.3').")
    name: str = Field(..., description="WBS node name.")
    parent_id: str | None = Field(
        default=None, description="Parent WBS ID, or None for root nodes."
    )


class PredecessorLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predecessor_id: str = Field(..., description="Predecessor activity ID.")
    type: Literal["FS", "SS", "FF", "SF"] = Field(
        ..., description="Relationship type: Finish-Start, Start-Start, Finish-Finish, Start-Finish."
    )
    lag_days: float = Field(
        default=0.0, description="Lag in calendar days (positive = delay, negative = lead)."
    )


class ActivityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: str = Field(..., description="Unique activity identifier.")
    name: str = Field(..., description="Activity name.")
    wbs_id: str = Field(..., description="WBS node this activity belongs to.")
    start_date: str = Field(..., description="Planned or early start date (ISO).")
    finish_date: str = Field(..., description="Planned or early finish date (ISO).")
    duration_days: float = Field(..., description="Original duration in calendar days.")
    total_float_days: float = Field(
        ..., description="Total float in calendar days. Zero or negative = critical."
    )
    percent_complete: float = Field(..., description="Percent complete (0–100).")
    predecessors: list[PredecessorLink] = Field(
        default_factory=list, description="Predecessor relationships."
    )
    is_critical: bool = Field(
        default=False, description="True if this activity is on the critical path."
    )
    is_milestone: bool = Field(default=False, description="True if this is a milestone.")


class ParseWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str = Field(
        ...,
        description="Location in the file where the warning occurred (e.g. activity ID, line number).",
    )
    message: str = Field(..., description="Description of the parse warning.")


class ParsedScheduleMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_label: str
    source_file: str = Field(..., description="Echoed file_ref from input.")
    file_format: str = Field(..., description="Echoed file_format from input.")
    data_date: str = Field(..., description="Schedule data date (ISO).")
    start_date: str = Field(..., description="Project start date (ISO).")
    finish_date: str = Field(..., description="Project forecast finish date (ISO).")
    activity_count: int = Field(..., description="Total number of activities parsed.")
    milestone_count: int = Field(..., description="Total number of milestones parsed.")
    wbs_tree: list[WbsNode] = Field(
        default_factory=list, description="Work Breakdown Structure hierarchy."
    )
    activities: list[ActivityRecord] = Field(
        default_factory=list, description="Full activity list."
    )
    critical_path_activities: list[str] = Field(
        default_factory=list,
        description="List of activity_ids on the critical path (total_float ≤ 0).",
    )
    parse_warnings: list[ParseWarning] = Field(
        default_factory=list,
        description="Warnings encountered during parsing.",
    )


class ScheduleReaderOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["parsed_schedule"] = Field(
        default="parsed_schedule",
        description="Always 'parsed_schedule' for routing.",
    )
    metadata: ParsedScheduleMetadata = Field(..., description="Full parsed schedule data.")
    disclaimer: str = Field(
        default=(
            "AI-generated analysis based on the provided inputs. "
            "Verify against project records before acting on it."
        ),
        description="Canonical AI disclaimer (softer variant).",
    )
