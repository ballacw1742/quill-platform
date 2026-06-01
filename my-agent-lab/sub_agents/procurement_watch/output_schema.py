from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class ProcurementWatchOutputOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: str = Field(...)
    summary_metrics: dict[str, Any] = Field(...)
    watch_items: list[dict[str, Any]] = Field(...)
    escalations_top_3: list[dict[str, Any]] = Field(...)
    trend_observations: list[str] = Field(...)
    confidence: float = Field(...)
