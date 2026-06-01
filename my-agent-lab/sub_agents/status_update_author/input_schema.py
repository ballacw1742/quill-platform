from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class StatusUpdateAuthorInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    project: dict[str, Any] | None = Field(default=None, description="Input field 'project'")
    period: dict[str, Any] | None = Field(default=None, description="Input field 'period'")
    data_freshness: dict[str, Any] | None = Field(default=None, description="Input field 'data_freshness'")
    context: dict[str, Any] | None = Field(default=None, description="Input field 'context'")
