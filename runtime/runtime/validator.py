"""JSON Schema validation (Draft 2020-12)."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


def validate_output(payload: dict[str, Any], schema: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate `payload` against `schema`.

    Returns (ok, errors). `errors` is a list of human-readable strings.
    """
    validator = Draft202012Validator(schema)
    errors: list[ValidationError] = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    if not errors:
        return True, []
    msgs = []
    for err in errors:
        loc = ".".join(str(p) for p in err.absolute_path) or "<root>"
        msgs.append(f"{loc}: {err.message}")
    return False, msgs


__all__ = ["validate_output"]
