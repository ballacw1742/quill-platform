from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class ContractExtractorInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    upload_id: str | None = Field(default=None, description="Input field 'upload_id'")
    project_label: str | None = Field(default=None, description="Input field 'project_label'")
    notes: str | None = Field(default=None, description="Input field 'notes'")
    files: list[dict[str, Any]] | None = Field(default=None, description="Input field 'files'")
