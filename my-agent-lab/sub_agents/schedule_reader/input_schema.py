"""Input schema for the schedule_reader (Schedule File Parser) agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ScheduleReaderInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_label: str = Field(..., description="Free-text project identifier.")
    file_ref: str = Field(
        ...,
        description=(
            "Path or URI to the schedule file. "
            "Can be a local path (e.g. '/data/schedules/project.xer'), "
            "GCS URI (e.g. 'gs://bucket/key'), "
            "or MinIO/S3 URI (e.g. 's3://bucket/project.mpp')."
        ),
    )
    file_format: Literal["xer", "mpp", "p6xml", "csv"] = Field(
        ...,
        description="File format of the schedule file. Determines which parser is used.",
    )
