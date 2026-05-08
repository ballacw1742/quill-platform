"""Agent prompt + schema loader.

Reads `agents/<agent_id>/system.md` from the prompts repo, parses the YAML
front-matter, and resolves the referenced JSON schema (repo-relative).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from runtime.config import Config, get_config

_FRONTMATTER_DELIM = "---"


@dataclass(frozen=True)
class AgentSpec:
    """Parsed view of a single agent prompt + its output schema."""

    agent_id: str
    version: str
    default_model: str
    upgrade_model: str | None
    output_schema_ref: str
    trust_tier_default: str
    system_prompt: str
    prompt_path: Path
    schema_path: Path
    schema: dict[str, Any]
    raw_frontmatter: dict[str, Any]


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split YAML front-matter from prompt body. Raises on malformed input."""
    if not text.lstrip().startswith(_FRONTMATTER_DELIM):
        raise ValueError("system.md missing leading '---' front-matter delimiter")

    # Find first delimiter line (leading) then the closing one.
    lines = text.splitlines()
    # Index of opening `---`
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == _FRONTMATTER_DELIM)
    except StopIteration as e:
        raise ValueError("system.md missing opening '---'") from e
    try:
        end = next(
            i for i, ln in enumerate(lines[start + 1 :], start=start + 1) if ln.strip() == _FRONTMATTER_DELIM
        )
    except StopIteration as e:
        raise ValueError("system.md missing closing '---'") from e

    fm_text = "\n".join(lines[start + 1 : end])
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    fm = yaml.safe_load(fm_text) or {}
    if not isinstance(fm, dict):
        raise ValueError("front-matter must be a YAML mapping")
    return fm, body


def load_agent(agent_id: str, *, config: Config | None = None) -> AgentSpec:
    """Load an agent's prompt + schema from the prompts repo."""
    cfg = config or get_config()
    prompt_path = cfg.prompts_repo_path / "agents" / agent_id / "system.md"
    if not prompt_path.is_file():
        raise FileNotFoundError(f"agent prompt not found: {prompt_path}")

    text = prompt_path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(text)

    required = ("agent_id", "version", "default_model", "output_schema", "trust_tier_default")
    missing = [k for k in required if k not in fm]
    if missing:
        raise ValueError(f"front-matter missing required keys {missing} in {prompt_path}")

    if fm["agent_id"] != agent_id:
        raise ValueError(
            f"front-matter agent_id={fm['agent_id']!r} does not match directory {agent_id!r}"
        )

    schema_ref = str(fm["output_schema"])
    # Schemas are repo-relative.
    schema_path = (cfg.prompts_repo_path / schema_ref).resolve()
    if not schema_path.is_file():
        # Fall back to agent-local resolution
        alt = (prompt_path.parent / schema_ref).resolve()
        if alt.is_file():
            schema_path = alt
        else:
            raise FileNotFoundError(
                f"output_schema not found: tried {schema_path} and {alt}"
            )

    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    return AgentSpec(
        agent_id=str(fm["agent_id"]),
        version=str(fm["version"]),
        default_model=str(fm["default_model"]),
        upgrade_model=str(fm["upgrade_model"]) if fm.get("upgrade_model") else None,
        output_schema_ref=schema_ref,
        trust_tier_default=str(fm["trust_tier_default"]),
        system_prompt=body,
        prompt_path=prompt_path,
        schema_path=schema_path,
        schema=schema,
        raw_frontmatter=fm,
    )


__all__ = ["AgentSpec", "load_agent"]
