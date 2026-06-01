from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class KnowledgeManagerInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    trigger: str | None = Field(default=None, description="Input field 'trigger'")
    context: str | None = Field(default=None, description="Input field 'context'")
    relevant_artifact_ids: list[str] | None = Field(default=None, description="Input field 'relevant_artifact_ids'")
    decision_or_lesson: str | None = Field(default=None, description="Input field 'decision_or_lesson'")
