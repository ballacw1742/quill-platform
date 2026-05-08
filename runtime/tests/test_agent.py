from __future__ import annotations

import json

import httpx
import pytest

from runtime.agent import Agent
from runtime.llm_client import LLMClient, LLMResponse
from runtime.queue_client import QueueClient


class _FakeLLM(LLMClient):
    def __init__(self, *, text: str, model_used: str = "claude-sonnet-4-6") -> None:
        # Bypass parent __init__ requirements.
        self._text = text
        self._model_used = model_used

    async def call_llm(self, **kwargs):
        return LLMResponse(
            text=self._text,
            model_used=self._model_used,
            input_tokens=42,
            output_tokens=17,
            latency_ms=125,
            attempts=1,
            fell_back=False,
        )


def _queue_client(handler, cfg):
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(base_url=cfg.queue_api_url, transport=transport)
    return QueueClient(cfg, client=http)


@pytest.mark.asyncio
async def test_agent_run_happy_path_no_submit(demo_config):
    output = {"confidence": 0.91, "verdict": "approve"}
    text = f"Sure! ```json\n{json.dumps(output)}\n```"
    llm = _FakeLLM(text=text)
    agent = Agent("demo-agent", config=demo_config, llm=llm)
    run = await agent.run({"foo": "bar"}, submit_to_queue=False)
    assert run.error is None
    assert run.validation_ok
    assert run.output == output
    assert run.lane_decision is not None
    assert run.lane_decision.lane == 2  # tier-0-mandatory, clean
    assert run.input_hash and run.output_hash
    assert run.tokens_used == {"input": 42, "output": 17}


@pytest.mark.asyncio
async def test_agent_run_invalid_output_marks_error(demo_config):
    bad = {"confidence": "not a number", "verdict": "approve"}
    text = f"```json\n{json.dumps(bad)}\n```"
    llm = _FakeLLM(text=text)
    agent = Agent("demo-agent", config=demo_config, llm=llm)
    run = await agent.run({"foo": "bar"}, submit_to_queue=False)
    assert not run.validation_ok
    assert run.error == "schema_validation_failed"
    assert run.lane_decision is None  # we don't route invalid outputs


@pytest.mark.asyncio
async def test_agent_run_unparseable_output(demo_config):
    llm = _FakeLLM(text="I'm just chatting, no JSON here.")
    agent = Agent("demo-agent", config=demo_config, llm=llm)
    run = await agent.run({"foo": "bar"}, submit_to_queue=False)
    assert run.error and run.error.startswith("json_extraction")


@pytest.mark.asyncio
async def test_agent_run_submits_to_queue(demo_config):
    output = {"confidence": 0.95, "verdict": "approve", "safety_flag": True, "cost_impact_flag": True}
    text = f"```json\n{json.dumps(output)}\n```"
    llm = _FakeLLM(text=text)

    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/approvals"
        captured["body"] = json.loads(req.content)
        return httpx.Response(201, json={"id": "appr-xyz", "lane": captured["body"]["lane"]})

    queue = _queue_client(handler, demo_config)
    agent = Agent("demo-agent", config=demo_config, llm=llm, queue=queue)
    run = await agent.run({"foo": "bar"}, submit_to_queue=True, required_approvers=["owner", "partner"])
    assert run.error is None, run.error
    assert run.approval_id == "appr-xyz"
    # safety + cost → dual approval lane 3
    assert run.lane_decision.lane == 3
    assert captured["body"]["lane"] == 3
    assert captured["body"]["agent_id"] == "demo-agent"
    assert captured["body"]["agent_input_hash"] == run.input_hash
    assert captured["body"]["agent_output_hash"] == run.output_hash
    await queue.aclose()


@pytest.mark.asyncio
async def test_agent_model_override(demo_config):
    output = {"confidence": 0.95, "verdict": "approve"}
    llm = _FakeLLM(text=f"```json\n{json.dumps(output)}\n```", model_used="override-model")
    agent = Agent("demo-agent", config=demo_config, llm=llm)
    run = await agent.run({"x": 1}, submit_to_queue=False, model_override="override-model")
    assert run.model_used == "override-model"
