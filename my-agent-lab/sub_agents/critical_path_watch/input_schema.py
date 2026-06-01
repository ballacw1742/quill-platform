"""Input schema for the critical_path_watch (Schedule Risk Watcher) agent."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ActivityRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    activity_id: str = Field(..., description="Unique activity identifier (e.g. 'A1050').")
    name: str = Field(..., description="Activity name.")
    start_date: str = Field(..., description="Planned start date (ISO).")
    finish_date: str = Field(..., description="Planned finish date (ISO).")
    duration_days: float = Field(..., description="Original or remaining duration in calendar days.")
    total_float_days: float = Field(
        ..., description="Total float in calendar days. Zero or negative = on critical path."
    )
    percent_complete: float = Field(..., description="Percent complete (0–100).")
    predecessors: list[str] = Field(
        default_factory=list,
        description="List of predecessor activity IDs.",
    )
    is_milestone: bool = Field(default=False, description="True if this is a milestone activity.")


class ScheduleSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    activities: list[ActivityRecord] = Field(
        ..., description="Full list of schedule activities."
    )
    data_date: str = Field(
        ..., description="ISO date the schedule snapshot reflects (the 'as-of' date)."
    )


class ActualRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    activity_id: str = Field(..., description="Activity ID matching the schedule snapshot.")
    actual_start: str | None = Field(default=None, description="Actual start date (ISO), if started.")
    actual_finish: str | None = Field(default=None, description="Actual finish date (ISO), if complete.")
    percent_complete: float = Field(..., description="Current percent complete (0–100).")
    note: str | None = Field(
        default=None, description="Free-text note from the scheduler (e.g. 'waiting on steel delivery')."
    )


class CriticalPathWatchInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_label: str = Field(..., description="Free-text project identifier.")
    schedule_snapshot: ScheduleSnapshot = Field(
        ..., description="Current schedule snapshot to analyze."
    )
    recent_actuals: list[ActualRecord] = Field(
        default_factory=list,
        description="Recent actual progress records to overlay on the schedule.",
    )
