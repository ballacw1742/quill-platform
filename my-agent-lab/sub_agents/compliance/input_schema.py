from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field


class ComplianceInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    query: str = Field(..., description="Natural-language question about compliance checklists, regulatory deadlines, or contract obligations.")
