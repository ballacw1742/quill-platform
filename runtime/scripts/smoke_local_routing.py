"""End-to-end smoke for local Gemma routing.

Bypasses the Anthropic SDK entirely. Calls the live Ollama server and asserts
the LLMResponse contract is honored.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from runtime.local_llm_client import LocalLLMClient
from runtime.model_router import ModelRouter
from runtime.agent_loader import AgentSpec


def _fake_spec() -> AgentSpec:
    fm = {
        "agent_id": "smoke",
        "version": "0.0.1",
        "default_model": "claude-opus-4-7",
        "output_schema": "schemas/none.schema.json",
        "trust_tier_default": "tier-0-mandatory",
        "cost_class": "local-preferred",
    }
    return AgentSpec(
        agent_id="smoke",
        version="0.0.1",
        default_model="claude-opus-4-7",
        upgrade_model="claude-opus-4-7",
        output_schema_ref="schemas/none.schema.json",
        trust_tier_default="tier-0-mandatory",
        system_prompt=(
            "You are a JSON-only classifier. Respond with a single JSON object "
            "with exactly two fields: {\"category\": string, \"confidence\": number}. "
            "No prose, no markdown."
        ),
        prompt_path=Path("/tmp/fake.md"),
        schema_path=Path("/tmp/fake.schema.json"),
        schema={"type": "object"},
        raw_frontmatter=fm,
    )


async def main() -> int:
    spec = _fake_spec()
    router = ModelRouter(local_client=LocalLLMClient())
    user = json.dumps(
        {"text": "Project schedule slipped 2 weeks due to weather and concrete delays"}
    )
    print("smoke: calling Gemma via Ollama…")
    resp = await router.call(spec=spec, system=spec.system_prompt, user=user)
    print(f"  backend       = {resp.backend}")
    print(f"  model_used    = {resp.model_used}")
    print(f"  latency_ms    = {resp.latency_ms}")
    print(f"  input_tokens  = {resp.input_tokens}")
    print(f"  output_tokens = {resp.output_tokens}")
    print(f"  fell_back     = {resp.fell_back}")
    print(f"  text          = {resp.text[:200]}")
    try:
        parsed = json.loads(resp.text)
        print(f"  parsed JSON   = {parsed}")
    except json.JSONDecodeError as e:
        print(f"  parsed JSON   = FAILED ({e})")
        return 1
    assert resp.backend == "ollama", f"expected ollama, got {resp.backend}"
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
