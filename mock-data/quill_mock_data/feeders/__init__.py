"""Feeders — generators that emit synthetic events for the dispatcher.

Each feeder exposes a `tick()` callable that returns a list of FeederEvent dicts.
Events are NOT directly posted to the API; the dispatcher routes them through
the runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=False,
    lstrip_blocks=False,
)


def render(template_name: str, **ctx: Any) -> str:
    return _jinja_env.get_template(template_name).render(**ctx)


@dataclass
class FeederEvent:
    """Generic synthetic event handed off to the dispatcher.

    `kind` is one of:
      - "rfi.new"
      - "submittal.new"
      - "dfr.new"
      - "procurement.update"
      - "hyperscaler.inbound"
    """

    kind: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "mock"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "payload": self.payload,
        }
