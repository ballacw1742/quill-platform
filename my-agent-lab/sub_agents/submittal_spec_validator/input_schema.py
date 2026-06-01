from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class SubmittalSpecValidatorInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    submittal: dict[str, Any] | None = Field(default=None, description="Input field 'submittal'")
    context: dict[str, Any] | None = Field(default=None, description="Input field 'context'")
