import json

import pytest

from app.tools import REGISTRY, run_tool, specs_for_allowlist
from app.tools.base import ToolNotAllowedError

EXPECTED_TOOLS = {
    "get_time",
    "quill_finance_summary",
    "quill_pipeline_summary",
    "quill_operations_summary",
    "quill_customers_summary",
    "quill_intelligence_brief",
    "quill_list_pending_approvals",
}


def test_registry_contains_v1_suite():
    assert EXPECTED_TOOLS.issubset(REGISTRY.keys())


def test_specs_only_include_allowlisted_tools():
    specs = specs_for_allowlist(["get_time"])
    assert [s["name"] for s in specs] == ["get_time"]


def test_specs_skip_unknown_names():
    specs = specs_for_allowlist(["get_time", "does_not_exist"])
    assert [s["name"] for s in specs] == ["get_time"]


async def test_run_tool_denies_off_allowlist():
    with pytest.raises(ToolNotAllowedError):
        await run_tool("quill_finance_summary", {}, ["get_time"])


async def test_run_tool_executes_allowed():
    out = await run_tool("get_time", {}, ["get_time"])
    assert "20" in out  # a year appears


async def test_quill_tool_without_secret_returns_error_payload():
    # QUILL_AGENT_SECRET is empty in tests: tool must fail loudly, not silently.
    out = await run_tool(
        "quill_finance_summary", {}, ["quill_finance_summary"]
    )
    assert "QUILL_AGENT_SECRET not configured" in json.loads(out)["error"]
