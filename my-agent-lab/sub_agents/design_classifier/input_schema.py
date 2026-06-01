from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class DesignClassifierInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_label: str | None = Field(default=None, description="Input field 'project_label'")
    notes: str | None = Field(default=None, description="Input field 'notes'")
    uploaded_files: list[dict[str, Any]] | None = Field(default=None, description="Input field 'uploaded_files'")
    context: dict[str, Any] | None = Field(default=None, description="Input field 'context'")
