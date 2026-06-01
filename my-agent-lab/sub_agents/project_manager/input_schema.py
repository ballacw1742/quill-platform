from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class ProjectManagerInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    project: dict[str, Any] | None = Field(default=None, description="Input field 'project'")
    question: str | None = Field(default=None, description="Input field 'question'")
    depth: str | None = Field(default=None, description="Input field 'depth'")
    data_window: dict[str, Any] | None = Field(default=None, description="Input field 'data_window'")
    constraints: str | None = Field(default=None, description="Input field 'constraints'")
    relevant_data: list[dict[str, Any]] | None = Field(default=None, description="Input field 'relevant_data'")
