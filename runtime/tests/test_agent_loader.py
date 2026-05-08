from __future__ import annotations

import pytest

from runtime.agent_loader import load_agent


def test_load_agent_parses_frontmatter(demo_config):
    spec = load_agent("demo-agent", config=demo_config)
    assert spec.agent_id == "demo-agent"
    assert spec.version == "0.1.0"
    assert spec.default_model == "claude-sonnet-4-6"
    assert spec.upgrade_model == "claude-opus-4-7"
    assert spec.trust_tier_default == "tier-0-mandatory"
    assert "Demo Agent" in spec.system_prompt
    assert spec.schema["type"] == "object"
    # Front-matter should NOT leak into the system prompt body
    assert "agent_id: demo-agent" not in spec.system_prompt


def test_load_agent_missing_dir_raises(demo_config):
    with pytest.raises(FileNotFoundError):
        load_agent("does-not-exist", config=demo_config)


def test_load_agent_missing_frontmatter(tmp_path, demo_config, monkeypatch):
    target = demo_config.prompts_repo_path / "agents" / "broken"
    target.mkdir(parents=True)
    (target / "system.md").write_text("no frontmatter here", encoding="utf-8")
    with pytest.raises(ValueError):
        load_agent("broken", config=demo_config)


def test_load_agent_id_mismatch(demo_config):
    target = demo_config.prompts_repo_path / "agents" / "wrong-id"
    target.mkdir(parents=True)
    (target / "system.md").write_text(
        "---\nagent_id: not-wrong-id\nversion: 0.1.0\ndefault_model: x\n"
        "output_schema: schemas/demo.schema.json\ntrust_tier_default: tier-0-mandatory\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="agent_id"):
        load_agent("wrong-id", config=demo_config)
