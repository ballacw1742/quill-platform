from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class RfiClassificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rfi_id: str = Field(...)
    discipline: Literal["architectural", "structural", "civil", "mechanical", "electrical", "plumbing", "fire_protection", "low_voltage", "controls_bms", "process_cooling", "site_utilities", "multi_discipline", "unknown"] = Field(...)
    secondary_disciplines: list[str] | None = Field(default=None, description="Used when discipline = 'multi_discipline'.")
    category: Literal["spec_clarification", "drawing_conflict", "field_condition", "design_change_request", "submittal_question", "constructability", "code_compliance", "scope_clarification", "schedule", "cost", "other"] = Field(...)
    priority: Literal["P1-critical", "P2-high", "P3-normal", "P4-low"] = Field(...)
    suggested_responder_role: str = Field(..., description="Role name, not a person, e.g. 'electrical_engineer_of_record'.")
    cost_impact_flag: bool = Field(...)
    schedule_impact_flag: bool = Field(...)
    safety_flag: bool = Field(...)
    summary: str = Field(..., description="1-3 sentence neutral summary of what's being asked.")
    key_questions: list[str] | None = Field(default=None, description="Atomic sub-questions extracted from the RFI body.")
    citations: list[dict[str, Any]] = Field(...)
    duplicate_of: str | None | None = Field(default=None, description="RFI ID of a likely duplicate, or null.")
    escalation_reasons: list[str] | None = Field(default=None)
    confidence: float = Field(...)
