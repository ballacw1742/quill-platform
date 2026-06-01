"""progress_capture sub-agent — Site photo/video to structured progress.

Ported from agentic-pmo-prompts/agents/progress-capture/.
"""
from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from .input_schema import ProgressCaptureInput
from .output_schema import ProgressCaptureOutput
from tools.image_analysis import analyze_image_tool

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="progress_capture",
    model=MODEL,
    description=(
        "Analyzes site photos and videos to produce a structured progress assessment: "
        "percent complete by visible scope, quality observations, safety observations, "
        "and delta vs. prior capture."
    ),
    instruction=_INSTRUCTION,
    input_schema=ProgressCaptureInput,
    output_schema=ProgressCaptureOutput,
    tools=[analyze_image_tool],
)
