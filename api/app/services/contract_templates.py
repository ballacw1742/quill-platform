"""Contract templates service — Sprint Contracts.3.

Loads template metadata (YAML frontmatter) and body from the agentic-pmo-prompts
templates/contracts/ directory.

Cache
-----
Module-level in-memory cache keyed by (template_id, file_mtime).  A call to
``list_templates()`` or ``get_template()`` triggers a staleness check against
the file's current mtime; if the file has changed the cache entry is evicted
and rebuilt.

Templates directory
-------------------
Resolved from:
  1. ``CONTRACTS_TEMPLATES_PATH`` env var  (override for tests / Docker)
  2. Relative path from this file:
        api/app/services/contract_templates.py
        → up 4 dirs → quill-platform/
        → agentic-pmo-prompts/templates/contracts/

INDEX.md is explicitly skipped — it is the registry, not a template.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("quill.contract_templates")

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _templates_dir() -> Path:
    env_val = os.environ.get("CONTRACTS_TEMPLATES_PATH")
    if env_val:
        return Path(env_val).resolve()
    # The agentic-pmo-prompts repo is a SIBLING of quill-platform under
    # the OpenClaw workspace, not a subdirectory. Walk up to the workspace
    # parent so we resolve to .../.openclaw/workspace/agentic-pmo-prompts/.
    # Path layout:
    #   api/app/services/contract_templates.py
    #     parents[0] = services/
    #     parents[1] = app/
    #     parents[2] = api/
    #     parents[3] = quill-platform/  (repo root)
    #     parents[4] = .openclaw/workspace/  (sibling of agentic-pmo-prompts)
    workspace_root = Path(__file__).resolve().parents[4]
    candidate = (workspace_root / "agentic-pmo-prompts" / "templates" / "contracts").resolve()
    if candidate.exists():
        return candidate
    # Fallback: legacy expectation that the prompts repo is nested under the
    # platform repo (kept for resilience in case of unusual layouts).
    repo_root = Path(__file__).resolve().parents[3]
    return (repo_root / "agentic-pmo-prompts" / "templates" / "contracts").resolve()


# ---------------------------------------------------------------------------
# YAML front-matter parser (no external dep needed — uses stdlib)
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split YAML frontmatter from body.

    Returns (frontmatter_dict, body_text).  If there is no leading '---'
    block the entire text is returned as body with an empty dict.
    """
    if not text.startswith("---"):
        return {}, text

    # Find the closing ---
    end_idx = text.find("\n---", 3)
    if end_idx == -1:
        return {}, text

    yaml_block = text[3:end_idx].strip()
    body = text[end_idx + 4:].lstrip("\n")

    try:
        import yaml  # type: ignore[import]
        data = yaml.safe_load(yaml_block) or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("contract_templates.yaml_parse_failed err=%s", exc)
        data = {}

    return data, body


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
# { template_id: {"mtime": float, "data": dict} }
_cache: dict[str, dict[str, Any]] = {}


def _load_template_file(path: Path) -> dict[str, Any] | None:
    """Read a single template .md file and return the fully-parsed dict."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log.warning("contract_templates.read_failed path=%s err=%s", path, exc)
        return None

    fm, body = _parse_frontmatter(text)
    template_id = fm.get("template_id") or path.stem
    return {
        "template_id": template_id,
        "contract_type": fm.get("contract_type", "other"),
        "display_name": fm.get("display_name", template_id),
        "version": str(fm.get("version", "0.1.0")),
        "required_variables": list(fm.get("required_variables") or []),
        "optional_variables": list(fm.get("optional_variables") or []),
        "jurisdiction_notes": str(fm.get("jurisdiction_notes") or ""),
        "suitable_for": str(fm.get("suitable_for") or ""),
        "body": body,
    }


def _get_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except Exception:  # noqa: BLE001
        return 0.0


def _refresh_cache() -> dict[str, dict[str, Any]]:
    """Scan the templates directory and refresh stale cache entries.

    Returns the current cache (after refresh).
    """
    templates_dir = _templates_dir()
    if not templates_dir.is_dir():
        log.warning(
            "contract_templates.dir_missing path=%s", templates_dir
        )
        return _cache

    for path in sorted(templates_dir.glob("*.md")):
        if path.name.lower() == "index.md":
            continue  # skip INDEX.md
        mtime = _get_mtime(path)
        cached = _cache.get(path.stem)
        if cached is not None and cached.get("mtime") == mtime:
            continue  # still fresh
        data = _load_template_file(path)
        if data is not None:
            _cache[path.stem] = {"mtime": mtime, "data": data}
            log.debug("contract_templates.loaded template_id=%s", data["template_id"])

    return _cache


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_templates() -> list[dict[str, Any]]:
    """Return metadata for all available templates (no body)."""
    _refresh_cache()
    results: list[dict[str, Any]] = []
    for entry in _cache.values():
        d = entry["data"]
        # Exclude body from list response
        results.append({k: v for k, v in d.items() if k != "body"})
    results.sort(key=lambda x: (x.get("contract_type", ""), x.get("template_id", "")))
    return results


def get_template(template_id: str) -> dict[str, Any] | None:
    """Return a single template's full data (frontmatter + body), or None."""
    _refresh_cache()
    for entry in _cache.values():
        if entry["data"].get("template_id") == template_id:
            return entry["data"]
    return None


__all__ = ["list_templates", "get_template"]
