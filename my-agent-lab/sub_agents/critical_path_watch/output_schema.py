"""Output schema for the critical_path_watch (Schedule Risk Watcher) agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CriticalActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: str = Field(..., description="Activity ID on the critical path.")
    name: str = Field(..., description="Activity name.")
    total_float_days: float = Field(..., description="Current total float (≤0 = critical).")
    percent_complete: float = Field(..., description="Current percent complete (0–100).")
    status: Literal["on_track", "at_risk", "slipping", "behind"] = Field(
        ...,
        description=(
            "on_track: progressing per plan. "
            "at_risk: minor concern. "
            "slipping: measurable delay developing. "
            "behind: already delayed."
        ),
    )


class AtRiskActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: str = Field(..., description="Activity ID trending toward the critical path.")
    name: str = Field(..., description="Activity name.")
    current_float_days: float = Field(
        ..., description="Current total float (positive but trending toward zero)."
    )
    predicted_finish: str = Field(
        ..., description="Predicted finish date based on current progress (ISO date)."
    )
    predicted_slip_days: float = Field(
        ..., description="Predicted slip in calendar days vs. planned finish."
    )
    root_cause: str = Field(
        ..., description="The agent's assessment of why this activity is falling behind."
    )
    recommended_action: str = Field(
        ..., description="Concrete action the project team should take to recover."
    )


class RecoveryOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option: str = Field(..., description="Description of the recovery strategy.")
    est_days_recovered: float = Field(
        ..., description="Estimated number of calendar days recovered if this option is implemented."
    )
    est_cost_usd: float | None = Field(
        default=None, description="Estimated incremental cost in USD, if quantifiable."
    )
    risk: str = Field(
        ..., description="Key risks or downsides of pursuing this recovery option."
    )


class CriticalPathStatusMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_label: str = Field(..., description="Project identifier, echoed from input.")
    data_date: str = Field(..., description="Schedule data date, echoed from input.")
    critical_path_activities: list[CriticalActivity] = Field(
        default_factory=list,
        description="Activities currently on the critical path (total_float ≤ 0).",
    )
    at_risk_activities: list[AtRiskActivity] = Field(
        default_factory=list,
        description=(
            "Activities NOT currently on the critical path but trending toward it. "
            "This is the headline section for the project team."
        ),
    )
    recovery_options: list[RecoveryOption] = Field(
        default_factory=list,
        description="Recommended recovery strategies for at-risk or slipping activities.",
    )
    summary: str = Field(
        ...,
        description=(
            "Chief-of-staff-voice 200-word executive summary of the current schedule health. "
            "Lead with the biggest risk, then the recommendation."
        ),
    )


class CriticalPathWatchOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["critical_path_status"] = Field(
        default="critical_path_status",
        description="Always 'critical_path_status' for routing.",
    )
    metadata: CriticalPathStatusMetadata = Field(..., description="Full schedule risk analysis.")
    disclaimer: str = Field(
        default=(
            "AI-generated analysis based on the provided inputs. "
            "Verify against project records before acting on it."
        ),
        description="Canonical AI disclaimer.",
    )
