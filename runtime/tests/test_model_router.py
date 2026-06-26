"""Tests for runtime.model_router — routing decision + dispatch."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from runtime.agent_loader import AgentSpec
from runtime.llm_client import LLMError, LLMResponse
from runtime.local_llm_client import LocalLLMError
from runtime.model_router import ModelRouter, decide_route


def _spec(
    *,
    cost_class: str | None = None,
    local_model: str | None = None,
    default_model: str = "claude-opus-4-7",
    upgrade_model: str | None = "claude-opus-4-7",
) -> AgentSpec:
    fm: dict[str, Any] = {
        "agent_id": "test-agent",
        "version": "0.0.1",
        "default_model": default_model,
        "output_schema": "schemas/none.schema.json",
        "trust_tier_default": "tier-0-mandatory",
    }
    if cost_class is not None:
        fm["cost_class"] = cost_class
    if local_model is not None:
        fm["local_model"] = local_model
    return AgentSpec(
        agent_id="test-agent",
        version="0.0.1",
        default_model=default_model,
        upgrade_model=upgrade_model,
        output_schema_ref="schemas/none.schema.json",
        trust_tier_default="tier-0-mandatory",
        system_prompt="system",
        prompt_path=Path("/tmp/system.md"),
        schema_path=Path("/tmp/none.schema.json"),
        schema={"type": "object"},
        raw_frontmatter=fm,
    )


# ----------------------------------------------------------------------
# decide_route — pure logic, no I/O
# ----------------------------------------------------------------------


def test_default_is_remote_only_when_cost_class_missing():
    d = decide_route(_spec())
    assert d.backend == "anthropic"
    assert d.model == "claude-opus-4-7"
    assert d.fallback_model is None
    assert "remote-only" in d.reason


def test_remote_only_explicit():
    d = decide_route(_spec(cost_class="remote-only"))
    assert d.backend == "anthropic"
    assert d.fallback_model is None


def test_local_preferred_routes_local_with_remote_fallback():
    d = decide_route(_spec(cost_class="local-preferred"))
    assert d.backend == "ollama"
    assert d.model == "gemma4:12b-mlx"
    assert d.fallback_model == "claude-opus-4-7"


def test_local_only_no_fallback():
    d = decide_route(_spec(cost_class="local-only"))
    assert d.backend == "ollama"
    assert d.fallback_model is None


def test_invalid_cost_class_defaults_to_remote_only(caplog):
    d = decide_route(_spec(cost_class="bogus"))
    assert d.backend == "anthropic"


def test_model_override_wins_and_picks_backend():
    # Anthropic-style name → remote
    d = decide_route(_spec(cost_class="local-only"), model_override="claude-sonnet-4-6")
    assert d.backend == "anthropic"
    assert d.model == "claude-sonnet-4-6"

    # Non-claude name → local
    d = decide_route(_spec(cost_class="remote-only"), model_override="llama3.1:70b")
    assert d.backend == "ollama"
    assert d.model == "llama3.1:70b"


def test_local_model_frontmatter_pin():
    d = decide_route(_spec(cost_class="local-preferred", local_model="qwen3:14b"))
    assert d.model == "qwen3:14b"


def test_kill_switch_forces_remote_for_local_classes(monkeypatch):
    monkeypatch.setenv("LOCAL_DISABLE", "1")
    d = decide_route(_spec(cost_class="local-preferred"))
    assert d.backend == "anthropic"
    assert "kill_switch" in d.reason

    d = decide_route(_spec(cost_class="local-only"))
    assert d.backend == "anthropic"


def test_kill_switch_doesnt_disturb_remote_routes(monkeypatch):
    monkeypatch.setenv("LOCAL_DISABLE", "1")
    d = decide_route(_spec(cost_class="remote-only"))
    assert d.backend == "anthropic"
    assert "kill_switch" not in d.reason


def test_local_model_env_default(monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_NAME", "gemma4:12b-mlx-q4")
    d = decide_route(_spec(cost_class="local-preferred"))
    assert d.model == "gemma4:12b-mlx-q4"


# ----------------------------------------------------------------------
# ModelRouter.call — async dispatch
# ----------------------------------------------------------------------


def _make_router_with_mocks() -> tuple[ModelRouter, MagicMock, MagicMock]:
    remote = MagicMock()
    remote.call_llm = AsyncMock()
    local = MagicMock()
    local.call = AsyncMock()
    router = ModelRouter(remote_client=remote, local_client=local)
    return router, remote, local


def test_router_remote_path():
    router, remote, local = _make_router_with_mocks()
    remote.call_llm.return_value = LLMResponse(
        text='{"ok": 1}',
        model_used="claude-opus-4-7",
        input_tokens=100,
        output_tokens=20,
        latency_ms=300,
        attempts=1,
        backend="anthropic",
    )

    resp = asyncio.run(
        router.call(
            spec=_spec(cost_class="remote-only"),
            system="sys",
            user="usr",
        )
    )
    assert resp.backend == "anthropic"
    assert remote.call_llm.await_count == 1
    assert local.call.await_count == 0


def test_router_local_path():
    router, remote, local = _make_router_with_mocks()
    local.call.return_value = {
        "text": '{"ok": 1}',
        "model_used": "gemma4:12b-mlx",
        "input_tokens": 80,
        "output_tokens": 15,
        "latency_ms": 9000,
    }

    resp = asyncio.run(
        router.call(
            spec=_spec(cost_class="local-preferred"),
            system="sys",
            user="usr",
        )
    )
    assert resp.backend == "ollama"
    assert resp.fell_back is False
    assert local.call.await_count == 1
    assert remote.call_llm.await_count == 0


def test_router_local_fallback_on_error():
    router, remote, local = _make_router_with_mocks()
    local.call.side_effect = LocalLLMError("connection refused")
    remote.call_llm.return_value = LLMResponse(
        text='{"ok": 1}',
        model_used="claude-opus-4-7",
        input_tokens=100,
        output_tokens=20,
        latency_ms=300,
        attempts=1,
        backend="anthropic",
    )

    resp = asyncio.run(
        router.call(
            spec=_spec(cost_class="local-preferred"),
            system="sys",
            user="usr",
        )
    )
    assert resp.backend == "anthropic"
    assert resp.fell_back is True
    assert local.call.await_count == 1
    assert remote.call_llm.await_count == 1


def test_router_local_only_raises_on_error():
    router, remote, local = _make_router_with_mocks()
    local.call.side_effect = LocalLLMError("oom")

    with pytest.raises(LLMError):
        asyncio.run(
            router.call(
                spec=_spec(cost_class="local-only"),
                system="sys",
                user="usr",
            )
        )
    assert remote.call_llm.await_count == 0
