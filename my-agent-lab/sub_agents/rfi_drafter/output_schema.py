from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class RfiResponseDraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rfi_id: str = Field(...)
    draft_response: str = Field(..., description="Plain-English response. May include numbered sub-answers.")
    answers_question_directly: bool = Field(..., description="True if the draft fully answers; false if it requests more info.")
    follow_up_questions: list[str] | None = Field(default=None, description="Required when answers_question_directly is false.")
    citations: list[dict[str, Any]] = Field(...)
    cost_impact: dict[str, Any] | None = Field(default=None)
    schedule_impact: dict[str, Any] | None = Field(default=None)
    requires_change_order: bool | None = Field(default=None)
    requires_design_team_review: bool | None = Field(default=None)
    escalation_reasons: list[str] | None = Field(default=None)
    confidence: float = Field(...)
