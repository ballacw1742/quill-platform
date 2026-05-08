"""Extract a JSON object from LLM output.

Strategy:
1. If the text contains a ```json ... ``` fenced block, parse the *first* one.
2. Otherwise, fall back to parsing the whole stripped text.
3. As a last resort, scan for the outer-most `{...}` and try to parse that.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(
    r"```(?:json|JSON)?\s*\n(?P<body>.*?)\n```",
    re.DOTALL,
)


class JSONExtractionError(ValueError):
    """Raised when no parseable JSON object can be found."""


def extract_json(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise JSONExtractionError("LLM output was empty")

    # 1) Fenced block
    m = _FENCE_RE.search(text)
    if m:
        body = m.group("body").strip()
        try:
            obj = json.loads(body)
        except json.JSONDecodeError as e:
            raise JSONExtractionError(
                f"Found ```json fence but body did not parse: {e.msg} at line {e.lineno} col {e.colno}"
            ) from e
        if not isinstance(obj, dict):
            raise JSONExtractionError("Fenced JSON did not contain a top-level object")
        return obj

    # 2) Bare body
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            pass  # fall through to (3)
        else:
            if isinstance(obj, dict):
                return obj
            raise JSONExtractionError("Top-level JSON was not an object")

    # 3) Outer braces scan
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last > first:
        candidate = stripped[first : last + 1]
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError as e:
            raise JSONExtractionError(
                f"Could not parse JSON from braces scan: {e.msg}"
            ) from e
        if not isinstance(obj, dict):
            raise JSONExtractionError("Brace-scan JSON was not an object")
        return obj

    raise JSONExtractionError("No JSON object found in LLM output")


__all__ = ["extract_json", "JSONExtractionError"]
