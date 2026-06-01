"""schedule_reader sub-agent — Schedule file parser.

Ported from agentic-pmo-prompts/agents/schedule-reader/.
"""
from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from .input_schema import ScheduleReaderInput
from .output_schema import ScheduleReaderOutput
from tools.schedule_parser import parse_schedule_file_tool

MODEL = "gemini-3.1-pro-preview"

_HERE = Path(__file__).parent
_INSTRUCTION = (_HERE / "instruction.md").read_text(encoding="utf-8")

agent = LlmAgent(
    name="schedule_reader",
    model=MODEL,
    description=(
        "Parses XER, MPP, P6 XML, and CSV schedule files into a structured "
        "parsed_schedule artifact with activities, WBS tree, critical path "
        "identification, and parse warnings."
    ),
    instruction=_INSTRUCTION,
    input_schema=ScheduleReaderInput,
    output_schema=ScheduleReaderOutput,
    tools=[parse_schedule_file_tool],
)
