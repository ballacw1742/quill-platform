from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class ProjectCoordinatorInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: str | None = Field(default=None, description="Input field 'artifact_type'")
    topic: str | None = Field(default=None, description="Input field 'topic'")
    scope: str | None = Field(default=None, description="Input field 'scope'")
    audience: str | None = Field(default=None, description="Input field 'audience'")
    constraints: dict[str, Any] | None = Field(default=None, description="Input field 'constraints'")
    inputs: list[dict[str, Any]] | None = Field(default=None, description="Input field 'inputs'")
