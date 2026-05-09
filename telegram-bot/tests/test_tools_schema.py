"""Tests for tool schema definitions (Phase B, Commit 2)."""

from __future__ import annotations

import jsonschema  # type: ignore
import pytest
from pydantic import BaseModel

from quill_bot.tools import TOOL_REGISTRY, anthropic_tool_specs

EXPECTED_TOOLS = {
    "search_approvals",
    "get_approval",
    "get_audit",
    "get_agent_status",
    "get_health",
    "dispatch_agent",
    "generate_deep_link",
    "current_time",
    "whoami",
    # Phase G.3 — estimates
    "get_estimate_status",
    "list_recent_estimates",
    "estimate_upload_link",
}


def test_all_expected_tools_registered() -> None:
    assert set(TOOL_REGISTRY.keys()) == EXPECTED_TOOLS


def test_every_registered_tool_has_executor_and_schema() -> None:
    for name, spec in TOOL_REGISTRY.items():
        assert spec.name == name
        assert spec.executor is not None, f"{name} missing executor"
        assert callable(spec.executor)
        assert isinstance(spec.input_schema, dict), f"{name} schema not dict"
        assert spec.input_schema.get("type") == "object"
        assert spec.description, f"{name} missing description"
        assert isinstance(spec.input_model, type) and issubclass(
            spec.input_model, BaseModel
        )


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOLS))
def test_each_input_schema_is_valid_json_schema(tool_name: str) -> None:
    spec = TOOL_REGISTRY[tool_name]
    # Validating the meta-schema confirms it's a well-formed JSON Schema.
    jsonschema.Draft202012Validator.check_schema(spec.input_schema)


def test_anthropic_tool_specs_shape() -> None:
    specs = anthropic_tool_specs()
    assert len(specs) == len(EXPECTED_TOOLS)
    for s in specs:
        assert set(s.keys()) >= {"name", "description", "input_schema"}
        assert s["name"] in EXPECTED_TOOLS


def test_required_fields_match_pydantic_models() -> None:
    """Required fields in the JSON schema should be a subset of Pydantic model fields."""
    for name, spec in TOOL_REGISTRY.items():
        required = set(spec.input_schema.get("required", []))
        model_fields = set(spec.input_model.model_fields.keys())
        assert required.issubset(model_fields), (
            f"{name}: required {required} not subset of model fields {model_fields}"
        )


def test_pydantic_validation_rejects_unknown_field() -> None:
    """Sanity: pydantic models should accept only declared fields where strict.

    Most of our models are tolerant by default; this test is loose — it just
    confirms validation actually runs.
    """
    spec = TOOL_REGISTRY["get_approval"]
    # Missing required 'id' must raise.
    with pytest.raises(Exception):
        spec.input_model.model_validate({})


def test_dispatch_agent_input_schema_documents_dry_run() -> None:
    spec = TOOL_REGISTRY["dispatch_agent"]
    desc = spec.description.lower()
    assert "dry" in desc and "run" in desc, (
        "dispatch_agent description should call out dry-run / confirmation."
    )


def test_generate_deep_link_intent_enum_complete() -> None:
    spec = TOOL_REGISTRY["generate_deep_link"]
    intents = spec.input_schema["properties"]["intent"]["enum"]
    assert set(intents) == {"approve", "reject", "edit", "view"}
