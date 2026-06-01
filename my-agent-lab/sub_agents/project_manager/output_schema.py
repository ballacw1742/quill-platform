from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class PmAnalysisMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., description="Project key (e.g. 'QPB1'). Drives Drive folder routing and search index partition.")
    question: str = Field(..., description="Verbatim copy of the question / ask the analysis answers. Mirrors the input so downstream consumers can route on it.")
    depth: Literal["quick", "detailed", "formal_memo"] = Field(..., description="Analytical depth: quick = 1–2 page bullet brief; detailed = full analysis with options & next steps; formal_memo = exec-ready memo with executive-summ")
    audience: Literal["internal", "partner", "owner"] | None = Field(default=None, description="Tone & lane. 'owner' forces tier-3 review (Charles approves before any owner-facing copy moves).")
    constraints: str | None | None = Field(default=None, description="Optional verbatim copy of any constraints from the input (timebox, budget, page limit, regulatory).")
    data_window: dict[str, Any] | None | None = Field(default=None, description="Inclusive ISO-date window the analysis pulled data over.")
    situation: str = Field(..., description="Plain statement of the current situation the analysis starts from. Facts only, with citations. No opinions, no recommendations.")
    analysis: str = Field(..., description="Reasoning showing how the situation was decomposed: drivers, constraints, dependencies, tradeoffs, calculations. Reasoning is shown, not summarized aw")
    options: list[Option] = Field(..., description="Decision options considered. At least one option is required even when the recommendation is to do nothing (label that option 'No action'). Options ar")
    recommendation: str = Field(..., description="The recommended option and the reasoning, in plain English. References the option label from options[] explicitly. Avoids hedging fluff. If recommenda")
    risks: list[Risk] = Field(..., description="Risks introduced by, or surfaced during, the analysis. Each entry has severity, likelihood, mitigation, and an owner role.")
    next_steps: list[NextStep] = Field(..., description="Concrete actions to advance the recommendation. Each entry has an action, owner role, due date, and dependencies.")
    claim_confidence: list[dict[str, Any]] | None = Field(default=None, description="Per-claim confidence overrides. Use when individual sections (e.g. Cost) are materially less confident than the artifact-level confidence. Each entry ")

class Option(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., description="Short label for the option (e.g. 'Accept the slip', 'Crash the schedule with a second crew', 'No action').")
    pros: list[str] = Field(...)
    cons: list[str] = Field(...)
    impact_summary: str = Field(..., description="Plain-English summary of the impact (cost, schedule, risk, scope) of taking this option.")
    estimated_cost_impact: dict[str, Any] | None | None = Field(default=None, description="Optional structured cost impact. If unknown, use null and explain in impact_summary; do not fabricate dollar figures.")
    estimated_schedule_impact_days: int | None | None = Field(default=None, description="Signed days of schedule impact. Negative = ahead of baseline / pulls in; positive = pushes out. Null when the option has no schedule impact or it cann")
    recommendation_rank: int = Field(..., description="1 = recommended option. 2..N = alternatives in order of preference. Ties are not allowed; if two options are genuinely equivalent, surface that under ")

class Risk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(...)
    severity: Literal["low", "medium", "high", "critical"] = Field(...)
    likelihood: Literal["low", "medium", "high"] = Field(...)
    mitigation: str = Field(..., description="Concrete mitigation plan; must be actionable, not aspirational ('monitor closely' alone is not a mitigation).")
    owner_role: str = Field(..., description="Role label (not a person's name unless the input explicitly named them) responsible for the mitigation.")

class NextStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(..., description="Imperative-mood action ('Issue PCO for chiller substitution to owner', 'Lock 2-week mobilization buffer in DH-2 sequence B').")
    owner_role: str = Field(...)
    due_date: str | None | None = Field(default=None, description="Inclusive ISO date when the action is due. Null when the action is gated on another step.")
    dependencies: list[str] | None = Field(default=None, description="Other actions or artifact IDs this action depends on. Plain-English labels are fine.")

class PmAnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["pm_analysis"] = Field(...)
    metadata: PmAnalysisMetadata = Field(...)
