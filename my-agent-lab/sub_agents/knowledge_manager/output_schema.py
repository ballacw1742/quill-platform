from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class KnowledgeEntryMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger: Literal["decision_logged", "incident", "milestone", "weekly_review"] = Field(..., description="Why this knowledge entry exists. 'decision_logged' = a deliberate choice was made and we want to remember it + its rationale. 'incident' = something w")
    decision_or_lesson: str = Field(..., description="The single durable takeaway, as plain English a future PM could act on without context. For decision_logged: the decision + the reasoning. For inciden")
    context_summary: str = Field(..., description="One- to two-paragraph summary of the situation that produced the lesson. Names projects, dates, scope. Plain narrative voice. PII is redacted before t")
    applicable_phases: list[Literal["pre-construction", "foundations", "vertical", "mep_rough_in", "mep_trim", "commissioning", "handover", "post-handover"]] = Field(..., description="Construction phases this entry is relevant to. A future PM searching for 'what did we learn during MEP rough-in' should find this if 'mep_rough_in' is")
    applicable_disciplines: list[str] = Field(..., description="Disciplines this entry touches (e.g. 'structural', 'electrical', 'mechanical', 'safety', 'procurement', 'controls', 'commissioning', 'civil', 'life_sa")
    search_tags: list[str] = Field(..., description="Lowercase, hyphen-separated search tags. The knowledge index uses these for full-text and faceted search. Examples: 'long-lead', 'chiller-substitution")
    related_artifact_ids: list[str] = Field(..., description="Artifact IDs (RFIs, submittals, PCOs, prior knowledge entries, status updates, DFRs, etc.) that back the claims in this entry. Every substantive claim")
    decision_owner: str = Field(..., description="Role of the person who owned the decision or lesson — e.g. 'owner_pm', 'gc_super', 'mep_lead', 'commissioning_agent', 'safety_director'. ALWAYS a role")
    decision_date: str = Field(..., description="Inclusive ISO date (YYYY-MM-DD) the decision was made or the event occurred. Drives chronological ordering in the knowledge index.")

class KnowledgeEntryOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["knowledge_entry"] = Field(...)
    metadata: KnowledgeEntryMetadata = Field(...)
