from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field


class SalesInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    query: str = Field(..., description="Natural-language question about deals, accounts, pipeline value, win rates, or activity.")
