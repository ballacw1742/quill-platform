"""JSON Schema validation (Draft 2020-12).

Resolves `https://agentic-pmo.local/schemas/...` $ref URLs by walking
the configured prompts repo's schemas/ directory at validation time, so
agent output schemas that extend pm_artifact_base via allOf validate
cleanly without an internet round-trip.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

# Cached registry. Built lazily on first use; re-built when the prompts
# repo path changes (rare — once per process lifetime in practice).
_REGISTRY = None  # type: ignore[var-annotated]
_REGISTRY_FOR_ROOT: Path | None = None


def _build_registry(schemas_root: Path):
    """Load every *.schema.json under `schemas_root` into a referencing.Registry."""
    try:
        from referencing import Registry, Resource  # type: ignore
        from referencing.jsonschema import DRAFT202012  # type: ignore
    except Exception:  # noqa: BLE001 — referencing is bundled with jsonschema 4.18+
        return None

    resources: list[tuple[str, Any]] = []
    if schemas_root.is_dir():
        for p in sorted(schemas_root.glob("*.schema.json")):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            sid = doc.get("$id")
            if not sid:
                continue
            resource = Resource(contents=doc, specification=DRAFT202012)
            resources.append((sid, resource))
    if not resources:
        return None
    return Registry().with_resources(resources)


def _get_registry():
    """Locate the prompts repo schemas/ dir via the runtime config."""
    global _REGISTRY, _REGISTRY_FOR_ROOT
    try:
        from runtime.config import get_config  # type: ignore
        cfg = get_config()
        root = (cfg.prompts_repo_path / "schemas").resolve()
    except Exception:  # noqa: BLE001
        return None
    if _REGISTRY is not None and _REGISTRY_FOR_ROOT == root:
        return _REGISTRY
    _REGISTRY = _build_registry(root)
    _REGISTRY_FOR_ROOT = root
    return _REGISTRY


def validate_output(payload: dict[str, Any], schema: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate `payload` against `schema`.

    Returns (ok, errors). `errors` is a list of human-readable strings.
    """
    registry = _get_registry()
    if registry is not None:
        validator = Draft202012Validator(schema, registry=registry)
    else:
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
