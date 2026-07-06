from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field


class FacilityOpsInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    query: str = Field(..., description="Natural-language question about campus status, incidents, PUE, uptime, or power.")
