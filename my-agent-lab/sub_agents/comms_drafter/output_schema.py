from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class CommsDraftMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    subject: str = Field(..., description="Subject line (or formal-letter 're:') for the draft. ≤140 chars to keep inbox previews intact.")
    body_markdown: str = Field(..., description="Body of the draft as GitHub-flavored Markdown. Mirrors the artifact's top-level body_markdown so the Documents tab can render it as the message previe")
    recipient_class: Literal["owner", "partner", "subcontractor", "vendor", "internal"] = Field(..., description="Recipient class. 'owner' forces tier-3 (Charles approves before any owner-facing copy moves). 'partner' is tier-2 with external-distribution flag. The")
    tone: Literal["formal", "direct", "friendly"] = Field(..., description="Tone of the draft. 'formal' = letter voice, third-person where appropriate. 'direct' = plain English, no fluff. 'friendly' = warm but still profession")
    recommended_channel: Literal["email", "procore", "sms", "phone", "in_person"] = Field(..., description="Recommended channel for the human to use when sending. The agent drafts the message; channel is a recommendation, not a delivery action.")
    recommended_sender_role: str = Field(..., description="Role label of the recommended sender (e.g. 'Project Director', 'Procurement Lead', 'GC Superintendent'). Use a person's name only when the input expli")
    tone_notes: str = Field(..., description="Short note for the reviewer on tone choices: why this register, why this length, any phrases the reviewer should consider editing for context the draf")
    contains_commitment: bool = Field(..., description="True when the draft contains language that could reasonably be read as a commitment (delivery date, cost cap, scope guarantee, warranty extension). Wh")
    recipient_name: str | None | None = Field(default=None, description="Optional recipient name; null if the input gave only a role.")
    recipient_role: str | None | None = Field(default=None, description="Optional recipient role label (e.g. 'Owner Construction Lead'). Null if the input did not provide one.")
    purpose: str | None = Field(default=None, description="Verbatim copy of the purpose from the input. Lets reviewers quickly see what the draft is meant to accomplish.")
    key_facts_used: list[str] | None = Field(default=None, description="Subset of input key_facts the draft relies on. The reviewer can confirm at a glance that the draft is grounded in what the team provided and didn't in")
    redactions: list[dict[str, Any]] | None = Field(default=None, description="Items the agent redacted or omitted from the draft (PII, safety-sensitive content, attorney-client material). The runtime adds 'pii_redacted' or 'safe")
    channel_hint_honored: bool | None | None = Field(default=None, description="True when the input provided a channel_hint and the agent honored it; false when the agent chose a different channel (and explained why in tone_notes)")

class CommsDraftOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["comms_draft"] = Field(...)
    metadata: CommsDraftMetadata = Field(...)
