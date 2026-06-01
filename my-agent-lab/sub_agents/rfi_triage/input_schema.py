from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class RfiTriageInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    rfi: dict[str, Any] | None = Field(default=None, description="Input field 'rfi'")
    context: dict[str, Any] | None = Field(default=None, description="Input field 'context'")
