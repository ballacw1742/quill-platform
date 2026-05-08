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
def cmd_run(
    agent_id: str,
    input_path: str,
    no_submit: bool,
    model_override: str | None,
    workflow: str | None,
    priority: str,
) -> None:
    """Run a single agent against a single input file."""
    payload = _read_input(input_path)
    cfg = get_config()
    agent = Agent(agent_id, config=cfg)
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

    The Sprint-1 API auto-creates `AgentRegistration` rows the first time an
    agent submits an approval. This command makes that explicit by submitting
    a tiny "registration ping" approval per agent (lane 2 by default, payload
    = {"_registration": true}). It then optionally PATCHes the row to apply
    `--lane` / `--trust-tier`.
    """
    cfg = get_config()
    from runtime.agent_loader import load_agent

    async def _go() -> dict[str, Any]:
        results: dict[str, Any] = {}
        async with QueueClient(cfg) as q:
            existing = {row["agent_id"] for row in await q.list_agents()}
            for aid in agent_ids:
                if aid in existing:
                    results[aid] = {"status": "already-registered"}
                else:
                    spec = load_agent(aid, config=cfg)
                    ping = {
                        "agent_id": spec.agent_id,
                        "agent_version": spec.version,
                        "workflow": f"{spec.agent_id}.registration",
                        "lane": 2,
                        "priority": "low",
                        "target_system": "none",
                        "payload": {"_registration": True, "default_model": spec.default_model},
                        "agent_confidence": 1.0,
                        "agent_reasoning": "registry registration ping",
                        "agent_model": spec.default_model,
                        "agent_prompt_version": "registration",
                    }
                    created = await q.create_approval(ping)
                    # Cancel immediately so the queue isn't polluted with reg pings
                    try:
                        await q.cancel(created["id"], reason="registry registration ping")
                    except Exception:
                        pass
                    results[aid] = {"status": "registered", "approval_id": created["id"]}

                # Apply lane / trust-tier overrides if requested
                if lane is not None or trust_tier is not None:
                    patch = {}
                    if lane is not None:
                        patch["default_lane"] = lane
                    if trust_tier is not None:
                        patch["trust_tier"] = trust_tier
                    try:
                        await q.update_agent(aid, patch)
                        results[aid]["patch"] = patch
                    except Exception as e:
                        results[aid]["patch_error"] = str(e)
        return results

    out = asyncio.run(_go())
    click.echo(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
