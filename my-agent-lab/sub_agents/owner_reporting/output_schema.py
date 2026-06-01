"""Output schema for the owner_reporting (Owner-Facing Project Report) agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReportPeriodEcho(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str
    end: str
    period_type: Literal["weekly", "biweekly", "monthly"]


class HeadlineMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_status: Literal["under", "on_budget", "over"] = Field(
        ..., description="Overall cost health."
    )
    cost_variance_pct: float = Field(
        ...,
        description=(
            "Cost variance as % of current budget. "
            "Positive = over budget, negative = under budget."
        ),
    )
    schedule_status: Literal["ahead", "on_schedule", "behind"] = Field(
        ..., description="Overall schedule health."
    )
    schedule_variance_days: float = Field(
        ...,
        description=(
            "Variance in calendar days vs. original completion. "
            "Positive = behind, negative = ahead."
        ),
    )
    safety_status: Literal["clean", "minor_incidents", "major_incidents"] = Field(
        ..., description="Safety health this period."
    )


class MilestoneSummaryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    planned_date: str
    actual_date: str | None = None
    status: Literal["complete", "on_track", "at_risk", "missed"]
    commentary: str = Field(
        ..., description="Agent's one-sentence commentary on this milestone's status."
    )


class ChangeOrderSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(..., description="Narrative summary of change order activity this period.")
    total_value_usd: float = Field(..., description="Sum of all change order values this period.")
    items: list[dict] = Field(default_factory=list, description="Echo of recent_changes input.")


class RiskSummaryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk: str
    likelihood: str
    impact: str
    mitigation: str
    owner: str


class RisksSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_risks: list[RiskSummaryItem] = Field(
        ..., description="Top 3–5 risks requiring owner awareness, ordered by severity."
    )
    mitigation_summary: str = Field(
        ...,
        description="2–3 sentence summary of the risk picture and mitigation posture.",
    )


class OwnerActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str = Field(..., description="What the owner needs to do or decide.")
    decision_needed_by: str | None = Field(
        default=None, description="Deadline for the owner's action (ISO date or relative)."
    )
    recommendation: str = Field(..., description="Agent's recommendation for the owner's action.")


class OwnerStatusReportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_label: str
    report_period: ReportPeriodEcho
    executive_summary: str = Field(
        ...,
        description=(
            "1-paragraph executive summary written for the owner. "
            "Lead with overall health, key accomplishments, and top concern."
        ),
    )
    headline_metrics: HeadlineMetrics
    milestones_section: list[MilestoneSummaryItem]
    change_orders_section: ChangeOrderSummary
    risks_section: RisksSection
    next_period_outlook: str = Field(
        ...,
        description="2–3 sentences on what's planned for the next period and key risks.",
    )
    action_items_for_owner: list[OwnerActionItem] = Field(
        default_factory=list,
        description="Items requiring the owner's decision or action.",
    )


class OwnerReportingOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["owner_status_report"] = Field(
        default="owner_status_report",
        description="Always 'owner_status_report' for routing.",
    )
    metadata: OwnerStatusReportMetadata = Field(..., description="Full owner status report.")
    disclaimer: str = Field(
        default=(
            "AI-generated analysis. This is not legal advice. "
            "Review with qualified counsel before relying on it for any binding decision."
        ),
        description="Canonical AI disclaimer.",
    )
