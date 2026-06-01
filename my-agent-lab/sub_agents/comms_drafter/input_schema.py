from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class CommsDrafterInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    recipient_class: str | None = Field(default=None, description="Input field 'recipient_class'")
    tone: str | None = Field(default=None, description="Input field 'tone'")
    purpose: str | None = Field(default=None, description="Input field 'purpose'")
    key_facts: list[str] | None = Field(default=None, description="Input field 'key_facts'")
    recipient_name: Any | None | None = Field(default=None, description="Input field 'recipient_name'")
    recipient_role: str | None = Field(default=None, description="Input field 'recipient_role'")
    subject_hint: str | None = Field(default=None, description="Input field 'subject_hint'")
    channel_hint: str | None = Field(default=None, description="Input field 'channel_hint'")
    sender_role: str | None = Field(default=None, description="Input field 'sender_role'")
