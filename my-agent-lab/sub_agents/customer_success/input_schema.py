from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field


class CustomerSuccessInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    query: str = Field(..., description="Natural-language question about customer health, support tickets, or account notes.")
