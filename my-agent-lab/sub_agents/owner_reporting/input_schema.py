"""Input schema for the owner_reporting (Owner-Facing Project Report) agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReportPeriod(BaseModel):
    model_config = ConfigDict(extra="allow")

    start: str = Field(..., description="Period start date (ISO).")
    end: str = Field(..., description="Period end date (ISO).")
    period_type: Literal["weekly", "biweekly", "monthly"] = Field(
        ..., description="Type of reporting period."
    )


class CurrentStatus(BaseModel):
    model_config = ConfigDict(extra="allow")

    original_budget_usd: float = Field(..., description="Original contract budget in USD.")
    current_budget_usd: float = Field(
        ..., description="Current budget including approved change orders."
    )
    cost_to_date_usd: float = Field(..., description="Total costs incurred to date in USD.")
    original_completion_date: str = Field(..., description="Original contract completion date (ISO).")
    current_forecast_completion_date: str = Field(
        ..., description="Current forecast completion date (ISO)."
    )
    percent_complete: float = Field(..., description="Overall project percent complete (0–100).")


class MilestoneRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(..., description="Milestone name.")
    planned_date: str = Field(..., description="Planned milestone date (ISO).")
    actual_date: str | None = Field(default=None, description="Actual completion date (ISO), if achieved.")
    status: Literal["complete", "on_track", "at_risk", "missed"] = Field(
        ..., description="Current milestone status."
    )


class ChangeOrderRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    co_number: str = Field(..., description="Change order number (e.g. 'CO-001').")
    summary: str = Field(..., description="One-line description of the change.")
    value_usd: float = Field(..., description="Change order value in USD.")
    schedule_days: float = Field(..., description="Schedule impact in calendar days.")
    status: str = Field(..., description="Status (e.g. 'Executed', 'Pending', 'Rejected').")


class OpenRfi(BaseModel):
    model_config = ConfigDict(extra="allow")

    rfi_id: str = Field(..., description="RFI identifier.")
    summary: str = Field(..., description="One-line RFI description.")
    days_open: int = Field(..., description="Number of days the RFI has been open.")
    status: str = Field(..., description="RFI status (e.g. 'Pending Response', 'Under Review').")


class SafetySummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    recordable_incidents: int = Field(..., description="Number of OSHA recordable incidents this period.")
    near_misses: int = Field(..., description="Number of near-miss events this period.")
    days_since_last_incident: int = Field(
        ..., description="Days since the last recordable incident."
    )


class RiskRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    risk: str = Field(..., description="Risk description.")
    likelihood: str = Field(..., description="Likelihood rating (e.g. 'High', 'Medium', 'Low').")
    impact: str = Field(..., description="Impact rating if the risk materializes.")
    mitigation: str = Field(..., description="Current mitigation strategy.")
    owner: str = Field(..., description="Person or organization responsible for managing this risk.")


class OwnerReportingInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_label: str = Field(..., description="Free-text project identifier.")
    report_period: ReportPeriod = Field(..., description="Reporting period details.")
    current_status: CurrentStatus = Field(..., description="Current cost, schedule, and progress status.")
    milestones: list[MilestoneRecord] = Field(
        default_factory=list, description="Key project milestones."
    )
    recent_changes: list[ChangeOrderRecord] = Field(
        default_factory=list, description="Change orders executed or pending this period."
    )
    open_rfis: list[OpenRfi] = Field(
        default_factory=list, description="Open RFIs that may need owner attention."
    )
    safety_summary: SafetySummary = Field(..., description="Safety performance this period.")
    risks_register: list[RiskRecord] = Field(
        default_factory=list, description="Active risks requiring owner awareness."
    )
