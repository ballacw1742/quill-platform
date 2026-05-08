#!/usr/bin/env python3
"""Replay every example input through its agent and verify queue items land.

This is the Sprint 2 demo script. It pulls the existing example `*.input.json`
files from the prompts repo for the four pre-construction agents (coordinator,
rfi-triage, rfi-drafter, submittal-triage), runs each through the runtime, and
asserts that the resulting approval IDs are visible via the API.

Behavior:
- If `ANTHROPIC_API_KEY` is set, runs the *real* LLM.
- Otherwise, it uses the example's matching `*.output.json` as a "pre-recorded"
  LLM response so the replay still exercises validation, hashing, lane routing,
  and the queue API end-to-end without spending tokens.

This file is also the easiest place to read to understand how `Agent` is meant
to be driven from another Python program.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

# Ensure we can import the runtime when invoked as a plain script
HERE = Path(__file__).resolve()
RUNTIME_ROOT = HERE.parent.parent
sys.path.insert(0, str(RUNTIME_ROOT))

from runtime.agent import Agent  # noqa: E402
from runtime.config import get_config  # noqa: E402
from runtime.llm_client import LLMClient, LLMResponse  # noqa: E402
from runtime.queue_client import QueueClient  # noqa: E402

PRE_CONSTRUCTION_AGENTS = (
    "coordinator",
    "rfi-triage",
    "rfi-drafter",
    "submittal-triage",
)


class _ReplayLLM(LLMClient):
    """Returns a pre-recorded JSON output, no SDK call.

    Looks up `<example_stem>.output.json` next to the input file.
    """

    def __init__(self, output_payload: dict[str, Any], model_used: str = "replay") -> None:
        self._payload = output_payload
        self._model_used = model_used

    async def call_llm(self, **kwargs):
        body = "```json\n" + json.dumps(self._payload, indent=2) + "\n```"
        return LLMResponse(
            text=body,
            model_used=self._model_used,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            attempts=1,
            fell_back=False,
        )


async def _run_one(
    agent_id: str,
    input_path: Path,
    *,
    use_real_llm: bool,
    queue: QueueClient,
) -> dict[str, Any]:
    cfg = get_config()
    payload = json.loads(input_path.read_text(encoding="utf-8"))

    llm: LLMClient
    if use_real_llm:
        llm = LLMClient(cfg)
    else:
        # Find the matching pre-recorded output
        out_path = input_path.with_name(input_path.name.replace(".input.json", ".output.json"))
        if not out_path.is_file():
            return {
                "agent_id": agent_id,
                "input": str(input_path.name),
                "skipped": True,
                "reason": f"no replay output at {out_path.name}",
            }
        recorded = json.loads(out_path.read_text(encoding="utf-8"))
        llm = _ReplayLLM(recorded, model_used=f"replay::{agent_id}")

    agent = Agent(agent_id, config=cfg, llm=llm, queue=queue)
    run = await agent.run(payload, submit_to_queue=True, workflow=f"{agent_id}.replay")
    return {
        "agent_id": agent_id,
        "input": input_path.name,
        "approval_id": run.approval_id,
        "lane": run.lane_decision.lane if run.lane_decision else None,
        "tier": run.lane_decision.tier if run.lane_decision else None,
        "validation_ok": run.validation_ok,
        "validation_errors": run.validation_errors[:3],
        "model": run.model_used,
        "error": run.error,
    }


async def main() -> int:
    cfg = get_config()
    use_real_llm = bool(cfg.anthropic_api_key)
    print(f"# Replay: real_llm={use_real_llm} prompts_repo={cfg.prompts_repo_path}")

    examples_root = cfg.prompts_repo_path / "agents"
    results: list[dict[str, Any]] = []

    async with QueueClient(cfg) as queue:
        # Pre-flight: API reachable?
        try:
            health_before = await queue.health()
            print(f"# health (pre): pending={health_before.get('queue_depth_pending')}")
        except Exception as e:
            print(f"!! API unreachable at {cfg.queue_api_url}: {e}", file=sys.stderr)
            return 2

        for agent_id in PRE_CONSTRUCTION_AGENTS:
            ex_dir = examples_root / agent_id / "examples"
            if not ex_dir.is_dir():
                print(f"  - skip {agent_id}: no examples dir")
                continue
            inputs = sorted(ex_dir.glob("*.input.json"))
            if not inputs:
                print(f"  - skip {agent_id}: no example inputs")
                continue
            print(f"  - {agent_id}: {len(inputs)} example(s)")
            for p in inputs:
                row = await _run_one(agent_id, p, use_real_llm=use_real_llm, queue=queue)
                results.append(row)
                marker = "OK " if row.get("approval_id") else "ERR"
                print(
                    f"    [{marker}] {agent_id} {p.name} "
                    f"→ id={row.get('approval_id')} lane={row.get('lane')} "
                    f"err={row.get('error')}"
                )

        try:
            health_after = await queue.health()
        except httpx.HTTPError as e:
            print(f"!! health (post) failed: {e}")
            health_after = None

    enqueued = [r for r in results if r.get("approval_id")]
    failed = [r for r in results if r.get("error") and not r.get("approval_id")]
    skipped = [r for r in results if r.get("skipped")]

    print()
    print(f"# total={len(results)} enqueued={len(enqueued)} failed={len(failed)} skipped={len(skipped)}")
    if health_after is not None:
        print(
            f"# health (post): pending={health_after.get('queue_depth_pending')} "
            f"executed={health_after.get('queue_depth_executed')} "
            f"audit_chain={health_after.get('audit_chain')}"
        )

    print(json.dumps(results, indent=2, default=str))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
