from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class SopMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["sop"] = Field(...)
    scope: str = Field(..., description="What this SOP covers and where it applies (project, building, discipline).")
    owner_role: str = Field(..., description="Role accountable for the SOP (e.g. 'Site Superintendent', 'PMO Lead'). Person names are not allowed; use roles.")
    review_cadence: str | None | None = Field(default=None, description="Optional: how often this SOP is reviewed (e.g. 'quarterly', 'after each phase').")
    numbered_steps: list[SopStep] = Field(...)

class SopStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(..., description="Step number, 1-indexed, monotonically increasing within the SOP.")
    title: str = Field(..., description="Short imperative step title (e.g. 'Inspect formwork before pour').")
    owner_role: str = Field(..., description="Role accountable for executing this step.")
    description: str = Field(..., description="What is done, how, and with what tools/forms.")
    criteria: str = Field(..., description="Acceptance / pass criteria for the step. How do you know it's done correctly?")

class RaciMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["raci"] = Field(...)
    scope: str = Field(...)
    roles: list[str] = Field(..., description="Role names (not person names). Columns of the RACI matrix.")
    activities: list[str] = Field(..., description="Activities or decisions. Rows of the RACI matrix.")
    assignments: list[RaciAssignment] = Field(..., description="Cell-level assignments. For each (activity, role) pair you can record one or more responsibility codes. At least one R and one A must exist per activi")

class RaciAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity: str = Field(..., description="Must match a string in metadata.activities exactly.")
    role: str = Field(..., description="Must match a string in metadata.roles exactly.")
    responsibility: Literal["R", "A", "C", "I"] = Field(..., description="R=Responsible, A=Accountable, C=Consulted, I=Informed.")

class AgendaMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["agenda"] = Field(...)
    meeting_title: str = Field(...)
    date: str = Field(..., description="Meeting date (YYYY-MM-DD).")
    start_time: str | None | None = Field(default=None, description="Optional ISO time (HH:MM, 24-hour) the meeting starts.")
    duration_minutes: int = Field(...)
    location: str | None | None = Field(default=None)
    attendees: list[Attendee] = Field(...)
    items: list[AgendaItem] = Field(...)

class Attendee(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Display name. Use 'TBD' if unknown rather than inventing a name.")
    role: str = Field(...)
    required: bool | None = Field(default=None)
    organization: str | None | None = Field(default=None)

class AgendaItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: str = Field(..., description="Slot label (e.g. '0:00–0:15' or 'HH:MM').")
    duration_minutes: int | None | None = Field(default=None)
    topic: str = Field(...)
    owner: str = Field(..., description="Role or attendee name leading the topic.")
    prep: str | None | None = Field(default=None, description="Pre-read or prep work expected from attendees.")
    outcome: str | None | None = Field(default=None, description="Intended outcome (decision, info-share, status, action items).")

class ActionItemsMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["action_items"] = Field(...)
    scope: str = Field(..., description="Where these action items came from (e.g. 'CCB 2026-05-04 — design freeze packet').")
    source_meeting: str | None | None = Field(default=None, description="If captured from a meeting, the meeting title or minutes ref.")
    items: list[ActionItem] = Field(...)

class ActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Stable kebab/letter-number ID like 'AI-001'.")
    description: str = Field(...)
    owner: str = Field(..., description="Role accountable. Person names allowed only when explicitly provided in input; otherwise use a role.")
    due_date: str = Field(...)
    status: Literal["open", "in_progress", "done", "blocked"] = Field(...)
    blocker: str | None | None = Field(default=None, description="If status='blocked', the blocking reason (required when blocked, validator-side).")

class ProcessDocMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["process_doc"] = Field(...)
    scope: str = Field(...)
    owner_role: str = Field(...)
    audience: Literal["internal", "partner", "owner"] | None = Field(default=None)
    sections: list[ProcessDocSection] = Field(...)

class ProcessDocSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(...)
    body_markdown: str = Field(...)

class CoordinatorArtifactOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["coordinator_artifact"] = Field(...)
    metadata: Any = Field(..., description="Discriminated union by metadata.kind (sop | raci | agenda | action_items | process_doc). The Documents tab reads metadata.kind to render the subtype-s")
