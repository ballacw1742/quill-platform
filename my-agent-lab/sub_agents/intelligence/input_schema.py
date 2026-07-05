from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field


class IntelligenceInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    query: str = Field(..., description="Natural-language request for a cross-module executive summary, KPI rollup, or risk briefing.")
