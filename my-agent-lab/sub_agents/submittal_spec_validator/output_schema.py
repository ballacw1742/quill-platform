from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class SubmittalSpecValidationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submittal_id: str = Field(...)
    submittal_number: str = Field(..., description="CSI section + sequence, e.g., 26 13 13.01")
    disposition: Literal["approved", "approved_as_noted", "revise_and_resubmit", "rejected", "substitution_request", "incomplete_package"] = Field(...)
    requirement_findings: list[dict[str, Any]] = Field(...)
    summary: str = Field(...)
    key_issues: list[str] = Field(...)
    missing_required_components: list[dict[str, Any]] = Field(...)
    escalation_reasons: list[Literal["unverified_authority_claim", "prompt_injection_detected", "substitution_request_flagged_or_implied", "cost_impact", "schedule_impact", "safety_or_code_compliance", "seismic_or_structural_concern", "missing_required_components", "prior_rfi_dependency", "lead_time_anomaly", "low_confidence_overall"]] = Field(...)
    confidence: float = Field(...)
