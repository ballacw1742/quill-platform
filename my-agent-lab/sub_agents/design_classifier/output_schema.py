from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class AaceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_label: str = Field(..., description="Free-text label for this project / upload (e.g. 'QPB1 — DH-2 80% DD'). Provided by the user at upload time and echoed here for downstream routing/disp")
    class_: Literal["5", "4", "3", "2"] = Field(..., alias="class", description="AACE class the agent recommends. Class 1 and Class 0 are not allowed — full bid docs are required for Class 1, which is out of scope.")
    design_maturity_estimate_pct: float = Field(..., description="Agent's best estimate of design completeness as a percentage. AACE bands: Class 5 = 0-2%, Class 4 = 1-15%, Class 3 = 10-40%, Class 2 = 30-70%.")
    accuracy_range: dict[str, Any] | None = Field(default=None, description="AACE-recommended accuracy band for the chosen class. The agent reports it explicitly so reviewers can sanity-check.")
    supporting_evidence: list[EvidenceItem] = Field(..., description="Why the agent chose this class. Each item names a category (scope completeness, structural detail, MEP detail, civil detail, schedule/duration, etc.),")
    missing_for_next_class: list[MissingItem] = Field(..., description="What design info would be needed to support a higher (more accurate) class. Each item names a deliverable, why it matters, and which class it would un")
    uploaded_files: list[UploadedFile] = Field(..., description="Manifest of the files the user uploaded for classification. Status flags failed/partial extractions so reviewers can decide whether to re-upload.")
    design_disciplines_detected: list[str] | None = Field(default=None, description="Free-form tags for the disciplines the agent could see in the upload (e.g. architectural, structural, mechanical, electrical, plumbing, civil, fire-pr")

class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(..., description="Free-form category label set by the agent (e.g., 'scope_completeness', 'design_completeness', 'system_clarity', 'scope_definition', 'mechanical_detail")
    score: float = Field(..., description="0 = nothing in the package supports this dimension; 1 = fully detailed.")
    evidence: str = Field(..., description="Plain-English supporting note. Drawing references, sheet numbers, IFC entity counts, etc.")

class MissingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deliverable: str = Field(..., description="What's missing (e.g. 'Structural framing plans for DH-2', 'Equipment schedule with model numbers').")
    rationale: str = Field(..., description="Why it matters for the estimate.")
    would_unlock_class: Literal["4", "3", "2"] = Field(..., description="Which AACE class would become supportable once this is delivered. Class 1 is excluded.")

class UploadedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(...)
    kind: Literal["pdf", "ifc", "dwg", "dxf", "rvt", "other"] = Field(...)
    size_bytes: int = Field(...)
    extraction_status: Literal["ok", "partial", "failed"] = Field(...)
    extraction_summary: str | None = Field(default=None, description="Brief plain-English summary of what was extracted (page counts, entity counts, dominant content).")
    minio_key: str | None = Field(default=None, description="Storage key for the file in the upload bucket. Optional; not required for the agent's output but useful for the runtime.")

class AaceClassificationOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_type: Literal["aace_classification"] = Field(...)
    metadata: AaceMetadata = Field(...)
