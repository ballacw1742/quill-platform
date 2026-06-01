from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class CoordinatorInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    request: dict[str, Any] | None = Field(default=None, description="Input field 'request'")
    context: dict[str, Any] | None = Field(default=None, description="Input field 'context'")
