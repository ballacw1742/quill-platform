from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class ProcurementWatchInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    as_of: str | None = Field(default=None, description="Input field 'as_of'")
    inputs: dict[str, Any] | None = Field(default=None, description="Input field 'inputs'")
    context: dict[str, Any] | None = Field(default=None, description="Input field 'context'")
