"""Shared pytest fixtures."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

from runtime.config import Config


@pytest.fixture
def tmp_prompts_repo(tmp_path: Path) -> Path:
    """A minimal prompts repo with one agent + matching schema."""
    repo = tmp_path / "prompts"
    (repo / "agents" / "demo-agent").mkdir(parents=True)
    (repo / "schemas").mkdir(parents=True)

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["confidence", "verdict"],
        "properties": {
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "verdict": {"type": "string", "enum": ["approve", "reject"]},
            "cost_impact_flag": {"type": "boolean"},
            "schedule_impact_flag": {"type": "boolean"},
            "safety_flag": {"type": "boolean"},
        },
        "additionalProperties": True,
    }
    (repo / "schemas" / "demo.schema.json").write_text(json.dumps(schema), encoding="utf-8")

    front = textwrap.dedent(
        """
        ---
        agent_id: demo-agent
        version: 0.1.0
        default_model: claude-sonnet-4-6
        upgrade_model: claude-opus-4-7
        output_schema: schemas/demo.schema.json
        trust_tier_default: tier-0-mandatory
        ---

        # Demo Agent

        You are a demo agent. Always emit a JSON object with `confidence` and
        `verdict`.
        """
    ).lstrip()
    (repo / "agents" / "demo-agent" / "system.md").write_text(front, encoding="utf-8")
    return repo


@pytest.fixture
def demo_config(tmp_prompts_repo: Path) -> Config:
    return Config(
        prompts_repo_path=tmp_prompts_repo,
        queue_api_url="http://test.invalid",
        agent_shared_secret="test-secret",
        anthropic_api_key="test-key",
        log_level="WARNING",
    )


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Don't let real env vars leak into tests."""
    for k in (
        "PROMPTS_REPO_PATH",
        "QUEUE_API_URL",
        "AGENT_SHARED_SECRET",
        "ANTHROPIC_API_KEY",
        "DEFAULT_MODEL_OVERRIDE",
    ):
        monkeypatch.delenv(k, raising=False)
    # Make sure get_config cache is fresh for each test that calls it
    from runtime.config import get_config
    get_config.cache_clear()  # type: ignore[attr-defined]
    os.environ.setdefault("LOG_LEVEL", "WARNING")
