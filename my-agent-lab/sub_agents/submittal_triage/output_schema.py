from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class SubmittalReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submittal_id: str = Field(...)
    spec_section: str = Field(..., description="CSI MasterFormat section, e.g. '26 05 19'.")
    discipline: Literal["architectural", "structural", "civil", "mechanical", "electrical", "plumbing", "fire_protection", "low_voltage", "controls_bms", "process_cooling", "site_utilities", "multi_discipline", "unknown"] = Field(...)
    completeness: dict[str, Any] = Field(...)
    proposed_disposition: Literal["no_exceptions_taken", "make_corrections_noted", "revise_and_resubmit", "rejected", "for_record_only"] = Field(...)
    findings: list[dict[str, Any]] = Field(...)
    deviations_from_spec: list[dict[str, Any]] | None = Field(default=None)
    long_lead_flag: bool | None = Field(default=None, description="True if this is on the long-lead equipment list (transformers, switchgear, gensets, chillers, etc.).")
    schedule_impact_flag: bool | None = Field(default=None)
    citations: list[dict[str, Any]] = Field(...)
    escalation_reasons: list[str] | None = Field(default=None)
    confidence: float = Field(...)
