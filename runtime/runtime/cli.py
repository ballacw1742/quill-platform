"""`quill-runtime` command-line interface."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import click

from runtime.agent import Agent, AgentRun
from runtime.config import get_config
from runtime.queue_client import QueueClient


def _read_input(path: str) -> dict[str, Any]:
    if path == "-":
        data = sys.stdin.read()
    else:
        data = Path(path).read_text(encoding="utf-8")
    return json.loads(data)


def _print_run(run: AgentRun) -> None:
    out = run.to_dict()
    # Trim raw text in console output for readability
    if isinstance(out.get("raw_text"), str) and len(out["raw_text"]) > 1500:
        out["raw_text"] = out["raw_text"][:1500] + "...<truncated>"
    click.echo(json.dumps(out, indent=2, default=str))


@click.group()
@click.version_option(package_name="quill-runtime")
def main() -> None:
    """Quill Agent Runtime CLI."""


# ----------------------------------------------------------------------
# `quill-runtime run`
# ----------------------------------------------------------------------
@main.command("run")
@click.argument("agent_id")
@click.option("--input", "input_path", required=True, help="Path to JSON input or '-' for stdin.")
@click.option("--no-submit", is_flag=True, default=False, help="Do not POST to the queue API.")
@click.option("--model", "model_override", default=None, help="Override the agent's default model.")
@click.option("--workflow", default=None, help="Workflow tag (defaults to agent_id).")
@click.option("--priority", default="normal", show_default=True)
@click.option(
    "--replay-output",
    "replay_output",
    default=None,
    help="Skip the live LLM call and replay this pre-recorded output JSON file. Useful for demos without an API key.",
)
def cmd_run(
    agent_id: str,
    input_path: str,
    no_submit: bool,
    model_override: str | None,
    workflow: str | None,
    priority: str,
    replay_output: str | None,
) -> None:
    """Run a single agent against a single input file."""
    payload = _read_input(input_path)
    cfg = get_config()

    llm = None
    if replay_output:
        from runtime.llm_client import LLMClient, LLMResponse

        recorded = json.loads(Path(replay_output).read_text(encoding="utf-8"))
        body = "```json\n" + json.dumps(recorded, indent=2) + "\n```"

        class _Replay(LLMClient):
            def __init__(self) -> None:  # type: ignore[no-untyped-def]
                pass

            async def call_llm(self, **kwargs):  # type: ignore[override]
                return LLMResponse(
                    text=body,
                    model_used=f"replay::{agent_id}",
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=0,
                    attempts=1,
                    fell_back=False,
                )

        llm = _Replay()

    agent = Agent(agent_id, config=cfg, llm=llm) if llm else Agent(agent_id, config=cfg)
    run = asyncio.run(
        agent.run(
            payload,
            submit_to_queue=not no_submit,
            workflow=workflow,
            priority=priority,
            model_override=model_override,
        )
    )
    _print_run(run)
    if run.error:
        sys.exit(2)


# ----------------------------------------------------------------------
# `quill-runtime evals run`
# ----------------------------------------------------------------------
@main.group("evals")
def cmd_evals() -> None:
    """Run evals for an agent (delegates to the prompt repo's eval harness)."""


@cmd_evals.command("run")
@click.argument("agent_id")
@click.option("--limit", default=None, type=int, help="Limit eval count (passed through if supported).")
def cmd_evals_run(agent_id: str, limit: int | None) -> None:
    cfg = get_config()
    script = cfg.prompts_repo_path / "agents" / agent_id / "evals" / "run_evals.py"
    if not script.is_file():
        click.echo(f"no eval harness at {script}", err=True)
        sys.exit(2)
    cmd = [sys.executable, str(script)]
    if limit is not None:
        cmd += ["--limit", str(limit)]
    click.echo(f"$ {' '.join(cmd)}")
    rc = subprocess.call(cmd)
    sys.exit(rc)


# ----------------------------------------------------------------------
# `quill-runtime registry`
# ----------------------------------------------------------------------
@main.group("registry")
def cmd_registry() -> None:
    """Inspect / register agents with the queue API."""


@cmd_registry.command("list")
def cmd_registry_list() -> None:
    cfg = get_config()

    async def _go() -> Any:
        async with QueueClient(cfg) as q:
            return await q.list_agents()

    rows = asyncio.run(_go())
    click.echo(json.dumps(rows, indent=2, default=str))


@cmd_registry.command("register")
@click.argument("agent_ids", nargs=-1, required=True)
@click.option("--lane", default=None, type=int, help="Default lane to set (1/2/3).")
@click.option(
    "--trust-tier",
    "trust_tier",
    default=None,
    type=click.Choice(["tier-0-mandatory", "tier-1-spotcheck", "tier-2-auto"]),
    help="Trust tier to apply to all agents.",
)
def cmd_registry_register(
    agent_ids: tuple[str, ...],
    lane: int | None,
    trust_tier: str | None,
) -> None:
    """Register one or more agents.

    Calls `POST /v1/agents/{agent_id}` with the agent's front-matter-derived
    defaults. Idempotent — re-running the command updates the same rows.
    """
    cfg = get_config()
    from runtime.agent_loader import load_agent

    def _default_lane_for_tier(t: str) -> int:
        # Mirrors lane_router.route_lane() but at registration time we have no
        # output yet, so we just pick the agent's *baseline* lane.
        if t == "tier-2-auto":
            return 1
        return 2

    def _api_tier(t: str) -> str:
        # Map prompts-repo aliases to the API's TrustTier enum values.
        if t in ("tier-2-auto",):
            return "tier-2-auto"
        if t in ("tier-1-spotcheck", "tier-2-charles-approves"):
            return "tier-1-spotcheck"
        return "tier-0-mandatory"

    async def _go() -> dict[str, Any]:
        results: dict[str, Any] = {}
        async with QueueClient(cfg) as q:
            for aid in agent_ids:
                try:
                    spec = load_agent(aid, config=cfg)
                    body: dict[str, Any] = {
                        "version": spec.version,
                        "trust_tier": trust_tier or _api_tier(spec.trust_tier_default),
                        "default_lane": lane if lane is not None else _default_lane_for_tier(spec.trust_tier_default),
                        "enabled": True,
                        "notes": f"registered by quill-runtime; default_model={spec.default_model}",
                    }
                    row = await q.register_agent(aid, body)
                    results[aid] = {
                        "status": "registered",
                        "trust_tier": row.get("trust_tier"),
                        "default_lane": row.get("default_lane"),
                    }
                except Exception as e:  # noqa: BLE001
                    results[aid] = {"status": "error", "error": str(e)}
        return results

    out = asyncio.run(_go())
    click.echo(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
