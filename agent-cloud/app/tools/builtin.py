"""Built-in (non-Quill) tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.tools.base import Tool


async def _get_time(_args: dict[str, Any]) -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime(
        "%A %Y-%m-%d %H:%M:%S %Z"
    )


get_time = Tool(
    name="get_time",
    description="Get the current date and time (America/New_York).",
    handler=_get_time,
)

BUILTIN_TOOLS = [get_time]
