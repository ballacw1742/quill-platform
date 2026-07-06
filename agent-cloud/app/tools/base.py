"""Tool primitives: a Tool is data + an async handler returning a string."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


class ToolNotAllowedError(PermissionError):
    """The agent definition's allow-list does not include this tool."""


class ToolNotFoundError(KeyError):
    """No such tool in the registry."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: Callable[[dict[str, Any]], Awaitable[str]]
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    def spec(self) -> dict[str, Any]:
        """Anthropic tools[] entry."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
