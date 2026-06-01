from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class DailyBriefOutputOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: str = Field(...)
    header: dict[str, Any] = Field(...)
    top_of_mind: list[dict[str, Any]] = Field(...)
    approvals_pending: dict[str, Any] = Field(...)
    critical_path: dict[str, Any] = Field(...)
    procurement: dict[str, Any] = Field(...)
    rfis_submittals: dict[str, Any] = Field(...)
    field_yesterday: dict[str, Any] = Field(...)
    hyperscaler: dict[str, Any] = Field(...)
    calendar_today: list[dict[str, Any]] = Field(...)
    quill_health: dict[str, Any] = Field(...)
    recommendations: list[dict[str, Any]] = Field(...)
    prompt_injection_flag: bool | None = Field(default=None)
    confidence: float = Field(...)
