"""Output schema for the dfr_synthesizer (Daily Field Report Synthesizer) agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WeatherSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high_f: float
    low_f: float
    conditions: str
    precipitation_in: float | None = None


class CrewByTrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trade: str
    headcount: int
    hours: float


class CrewSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_headcount: int = Field(..., description="Total workers on site across all trades.")
    total_hours: float = Field(..., description="Total worker-hours across all trades.")
    by_trade: list[CrewByTrade] = Field(default_factory=list)


class WorkSummaryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str
    scope: str
    status: str = Field(
        ...,
        description="Status narrative (e.g. '65% complete — on schedule', 'Delayed — waiting on rebar delivery').",
    )
    photo_refs: list[str] = Field(
        default_factory=list,
        description="List of file_refs from photos that show this work item.",
    )


class DeliveryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str
    supplier: str
    quantity: str
    time_received: str


class EquipmentUtilization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment: str
    operator: str | None = None
    hours_used: float
    utilization_pct: float = Field(
        ...,
        description="Utilization as percentage of an 8-hour shift (hours_used / 8 × 100). Capped at 100.",
    )


class IssueLogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    description: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    action_owner: str | None = Field(
        default=None, description="Person or trade responsible for resolving the issue."
    )
    action_due: str | None = Field(
        default=None, description="Due date for resolution (ISO date or relative, e.g. 'Tomorrow EOD')."
    )


class DfrMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_label: str
    report_date: str
    summary: str = Field(..., description="One-paragraph executive summary of the day.")
    weather: WeatherSummary
    crew_summary: CrewSummary
    work_summary: list[WorkSummaryItem]
    deliveries: list[DeliveryItem]
    equipment_utilization: list[EquipmentUtilization]
    issues_log: list[IssueLogEntry]
    productivity_observations: str = Field(
        ...,
        description="The agent's plain-English read on the day's productivity and any patterns observed.",
    )
    tomorrow_outlook: str = Field(
        ...,
        description="Brief outlook for tomorrow: planned work, weather risk, deliveries expected, concerns.",
    )


class DfrSynthesizerOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["daily_field_report"] = Field(
        default="daily_field_report",
        description="Always 'daily_field_report' for routing.",
    )
    metadata: DfrMetadata = Field(..., description="Full Daily Field Report.")
    disclaimer: str = Field(
        default=(
            "AI-generated analysis. This is not legal advice. "
            "Review with qualified counsel before relying on it for any binding decision."
        ),
        description="Canonical AI disclaimer.",
    )
