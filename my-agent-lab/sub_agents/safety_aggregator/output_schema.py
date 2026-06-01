"""Output schema for the safety_aggregator (Safety Log Aggregator) agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SafetyPeriodEcho(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str
    end: str


class IncidentCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    near_misses: int
    first_aid: int
    recordable: int
    lost_time: int
    property_damage: int
    fatalities: int


class IncidentTypeFreq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., description="Incident type.")
    count: int = Field(..., description="Number of incidents of this type.")
    pct_of_total: float = Field(
        ..., description="Percentage of total incidents (0–100)."
    )


class RootCauseTrend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_cause: str = Field(..., description="Root cause category or description.")
    occurrences: int = Field(..., description="Number of incidents sharing this root cause.")
    recommended_systemic_action: str = Field(
        ...,
        description="Recommended systemic corrective action to address this root cause pattern.",
    )


class ToolboxTopicCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(..., description="Toolbox talk topic.")
    count: int = Field(..., description="Number of times this topic was covered.")


class OutstandingCorrectiveAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_date: str = Field(..., description="Date of the originating incident.")
    action: str = Field(..., description="Description of the corrective action.")
    owner: str | None = Field(default=None, description="Person responsible for the action.")
    due: str | None = Field(default=None, description="Due date for the action (ISO or relative).")
    status: Literal["open", "in_progress", "closed"] = Field(..., description="Current status.")


class SafetyAggregationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_label: str
    period: SafetyPeriodEcho
    incident_counts: IncidentCounts = Field(
        ..., description="Counts by incident type for the period."
    )
    osha_recordable_rate: float | None = Field(
        default=None,
        description=(
            "OSHA Total Recordable Incident Rate (TRIR). "
            "Formula: (recordable + lost_time) × 200000 / total_hours_worked. "
            "Set to None if total_hours_worked is not available in the input."
        ),
    )
    top_incident_types: list[IncidentTypeFreq] = Field(
        default_factory=list,
        description="Top incident types by frequency, ordered by count descending.",
    )
    root_cause_trends: list[RootCauseTrend] = Field(
        default_factory=list,
        description="Root cause patterns identified across incidents.",
    )
    toolbox_topic_coverage: list[ToolboxTopicCoverage] = Field(
        default_factory=list,
        description="Summary of toolbox talk topics covered and frequency.",
    )
    outstanding_corrective_actions: list[OutstandingCorrectiveAction] = Field(
        default_factory=list,
        description="Open or in-progress corrective actions from incidents this period.",
    )
    period_summary: str = Field(
        ...,
        description=(
            "Plain-English summary of safety performance: overall health, key trends, "
            "top concern, and recommended focus for the next period."
        ),
    )


class SafetyAggregatorOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["safety_aggregation"] = Field(
        default="safety_aggregation",
        description="Always 'safety_aggregation' for routing.",
    )
    metadata: SafetyAggregationMetadata = Field(
        ..., description="Full safety aggregation report."
    )
    disclaimer: str = Field(
        default=(
            "AI-generated analysis based on the provided inputs. "
            "Verify against project records before acting on it."
        ),
        description="Canonical AI disclaimer (softer variant for non-legal outputs).",
    )
