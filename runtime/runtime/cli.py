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
from runtime.notifications import sentry as sentry_svc
from runtime.queue_client import QueueClient

# Initialize Sentry as early as possible — safe even with no DSN.
sentry_svc.init()


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
@click.option(
    "--no-cache",
    "no_cache",
    is_flag=True,
    default=False,
    help="Disable Anthropic prompt caching (Sprint-4 fix #9). Useful for cache-cold debugging.",
)
def cmd_run(
    agent_id: str,
    input_path: str,
    no_submit: bool,
    model_override: str | None,
    workflow: str | None,
    priority: str,
    replay_output: str | None,
    no_cache: bool,
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
            prompt_cache=not no_cache,
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

    # Sprint-4 fix #6: delegate the prompt-tier → API enum mapping to the
    # canonical normalizer in runtime.lane_router so we don't drift.
    from runtime.lane_router import normalize_trust_tier

    def _api_tier(t: str) -> str:
        return normalize_trust_tier(t)

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


# ----------------------------------------------------------------------
# `quill-runtime triage` — continuous triage daemon (Phase F.1)
# ----------------------------------------------------------------------
@main.group("triage")
def cmd_triage() -> None:
    """Continuous triage dispatcher — auto-runs agent chains on every event."""


@cmd_triage.command("start")
@click.option(
    "--source",
    "source_type",
    default=None,
    type=click.Choice(["mock", "webhook"]),
    help="Event source. Defaults to TRIAGE_EVENT_SOURCE env var or 'mock'.",
)
@click.option(
    "--log-path",
    default=None,
    help="Override path to dispatch.log (mock source only).",
)
@click.option(
    "--poll-interval",
    "poll_interval",
    default=None,
    type=float,
    help="Seconds between polls. Defaults to TRIAGE_POLL_INTERVAL_SECONDS or 5.",
)
def cmd_triage_start(
    source_type: str | None,
    log_path: str | None,
    poll_interval: float | None,
) -> None:
    """Boot the TriageDispatcher daemon (foreground)."""
    import os as _os

    from runtime.triage_dispatcher import (
        TriageDispatcher,
        build_default_source,
    )

    # Honor the TRIAGE_DISPATCHER_ENABLED gate per spec.
    enabled = _os.environ.get("TRIAGE_DISPATCHER_ENABLED", "true").lower()
    if enabled in ("0", "false", "no"):
        click.echo("TRIAGE_DISPATCHER_ENABLED=false; refusing to start.", err=True)
        sys.exit(1)

    source_type = source_type or _os.environ.get("TRIAGE_EVENT_SOURCE", "mock")
    if poll_interval is None:
        try:
            poll_interval = float(_os.environ.get("TRIAGE_POLL_INTERVAL_SECONDS", "5"))
        except ValueError:
            poll_interval = 5.0

    cfg = get_config()
    log_path_obj = Path(log_path) if log_path else None
    source = build_default_source(
        source_type=source_type,
        log_path=log_path_obj,
        poll_interval_s=poll_interval,
    )
    dispatcher = TriageDispatcher(config=cfg)

    click.echo(
        f"[triage] starting source={source_type} poll={poll_interval}s queue={cfg.queue_api_url}",
        err=True,
    )

    async def _run() -> None:
        await dispatcher.start(source)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo("[triage] interrupted; shutting down", err=True)
        sys.exit(0)


@cmd_triage.command("replay")
@click.argument("log_path")
@click.option(
    "--from-cursor/--no-from-cursor",
    default=False,
    help="Resume from existing cursor (default: replay full log).",
)
def cmd_triage_replay(log_path: str, from_cursor: bool) -> None:
    """Replay a dispatch.log file once (no polling), then exit."""
    from runtime.triage_dispatcher import (
        MockDataEventSource,
        TriageDispatcher,
    )

    log_p = Path(log_path)
    if not log_p.exists():
        click.echo(f"log not found: {log_p}", err=True)
        sys.exit(2)
    if not from_cursor:
        cursor = log_p.with_suffix(log_p.suffix + ".cursor")
        if cursor.exists():
            cursor.unlink()

    cfg = get_config()
    src = MockDataEventSource(log_p, poll_interval_s=0.1)
    dispatcher = TriageDispatcher(config=cfg)

    async def _run() -> None:
        # Stop after a single read pass — we set the source's stop event
        # immediately after consuming the existing file contents.
        async def _consumer() -> None:
            try:
                async for event in src:
                    await dispatcher.dispatch(event)
            finally:
                pass

        async def _stopper() -> None:
            # Give the consumer one full poll cycle to read the file.
            await asyncio.sleep(0.2)
            src.stop()
            dispatcher.stop()

        await asyncio.gather(_consumer(), _stopper())

    asyncio.run(_run())
    click.echo(
        json.dumps(
            {
                "events_seen": dispatcher.stats.events_seen,
                "chains_run": dispatcher.stats.chains_run,
                "chains_succeeded": dispatcher.stats.chains_succeeded,
                "chains_failed": dispatcher.stats.chains_failed,
                "events_skipped": dispatcher.stats.events_skipped,
            },
            indent=2,
        )
    )


# ----------------------------------------------------------------------
# `quill-runtime classify` — classification dispatcher daemon (Phase G.5)
# ----------------------------------------------------------------------
@main.group("classify")
def cmd_classify() -> None:
    """Classification dispatcher — runs design-classifier on queued estimates."""


@cmd_classify.command("start")
@click.option(
    "--poll-interval",
    "poll_interval",
    default=None,
    type=float,
    help="Seconds between polls. Defaults to CLASSIFY_POLL_INTERVAL_SECONDS or 10.",
)
@click.option(
    "--state-file",
    "state_file",
    default=None,
    help="Override path to the JSON state file.",
)
def cmd_classify_start(
    poll_interval: float | None,
    state_file: str | None,
) -> None:
    """Boot the ClassificationDispatcher daemon (foreground)."""
    import os as _os
    from pathlib import Path as _Path

    from runtime.classification_dispatcher import (
        ClassificationDispatcher,
        install_signal_handlers,
    )

    if poll_interval is None:
        try:
            poll_interval = float(
                _os.environ.get("CLASSIFY_POLL_INTERVAL_SECONDS", "10")
            )
        except ValueError:
            poll_interval = 10.0

    cfg = get_config()
    state_path = _Path(state_file) if state_file else None
    dispatcher = ClassificationDispatcher(
        config=cfg,
        poll_interval_s=poll_interval,
        state_file=state_path,
    )
    install_signal_handlers(dispatcher)

    click.echo(
        f"[classify] starting poll={poll_interval}s api={cfg.queue_api_url}",
        err=True,
    )

    async def _run() -> None:
        await dispatcher.start()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo("[classify] interrupted; shutting down", err=True)
        sys.exit(0)


@cmd_classify.command("status")
@click.option(
    "--state-file",
    "state_file",
    default=None,
    help="Override path to the JSON state file.",
)
def cmd_classify_status(state_file: str | None) -> None:
    """Print the classification dispatcher state (dispatched count, recent errors)."""
    from pathlib import Path as _Path

    from runtime.classification_dispatcher import ClassificationDispatcher

    state_path = _Path(state_file) if state_file else None
    dispatcher = ClassificationDispatcher(state_file=state_path)
    data = dispatcher.get_status_dict()
    click.echo(json.dumps(data, indent=2, default=str))


# ----------------------------------------------------------------------
# `quill-runtime estimate` — estimator dispatcher daemon (Phase G.6)
# ----------------------------------------------------------------------
# Subcommand name rationale: ``estimate`` is preferred over ``estimator``
# because it mirrors the verb used in the API route (``start_estimation``)
# and the state machine status (``estimating``). It reads naturally:
#   quill-runtime estimate start
#   quill-runtime estimate status
@main.group("estimate")
def cmd_estimate() -> None:
    """Estimator dispatcher — runs estimator-scheduler on classified estimates."""


@cmd_estimate.command("start")
@click.option(
    "--poll-interval",
    "poll_interval",
    default=None,
    type=float,
    help="Seconds between polls. Defaults to ESTIMATE_POLL_INTERVAL_SECONDS or 10.",
)
@click.option(
    "--state-file",
    "state_file",
    default=None,
    help="Override path to the JSON state file.",
)
def cmd_estimate_start(
    poll_interval: float | None,
    state_file: str | None,
) -> None:
    """Boot the EstimatorDispatcher daemon (foreground)."""
    import os as _os
    from pathlib import Path as _Path

    from runtime.estimator_dispatcher import (
        EstimatorDispatcher,
        install_signal_handlers,
    )

    if poll_interval is None:
        try:
            poll_interval = float(
                _os.environ.get("ESTIMATE_POLL_INTERVAL_SECONDS", "10")
            )
        except ValueError:
            poll_interval = 10.0

    cfg = get_config()
    state_path = _Path(state_file) if state_file else None
    dispatcher = EstimatorDispatcher(
        config=cfg,
        poll_interval_s=poll_interval,
        state_file=state_path,
    )
    install_signal_handlers(dispatcher)

    click.echo(
        f"[estimate] starting poll={poll_interval}s api={cfg.queue_api_url}",
        err=True,
    )

    async def _run() -> None:
        await dispatcher.start()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo("[estimate] interrupted; shutting down", err=True)
        sys.exit(0)


@cmd_estimate.command("status")
@click.option(
    "--state-file",
    "state_file",
    default=None,
    help="Override path to the JSON state file.",
)
def cmd_estimate_status(state_file: str | None) -> None:
    """Print the estimator dispatcher state (dispatched count, recent errors)."""
    from pathlib import Path as _Path

    from runtime.estimator_dispatcher import EstimatorDispatcher

    state_path = _Path(state_file) if state_file else None
    dispatcher = EstimatorDispatcher(state_file=state_path)
    data = dispatcher.get_status_dict()
    click.echo(json.dumps(data, indent=2, default=str))


# ----------------------------------------------------------------------
# `quill-runtime dev-chat` — dev-chat worker daemon (Sprint DC.1)
# ----------------------------------------------------------------------
@main.group("dev-chat")
def cmd_dev_chat() -> None:
    """Dev-chat worker — dispatches OpenClaw sub-agent tasks for /dev-chat."""


@cmd_dev_chat.command("start")
@click.option(
    "--simulate-agent",
    "simulate",
    is_flag=True,
    default=False,
    help="Simulate agent run locally (commits to origin/main; no OpenClaw calls).",
)
@click.option(
    "--poll-interval",
    "poll_interval",
    default=None,
    type=float,
    help="Seconds between polls. Defaults to DEV_CHAT_POLL_INTERVAL_SECONDS or 5.",
)
def cmd_dev_chat_start(simulate: bool, poll_interval: float | None) -> None:
    """Boot the DevChatWorker daemon (foreground)."""
    import os as _os

    from runtime.dev_chat_worker import DevChatWorker

    if poll_interval is None:
        try:
            poll_interval = float(_os.environ.get("DEV_CHAT_POLL_INTERVAL_SECONDS", "5"))
        except ValueError:
            poll_interval = 5.0

    api_url = _os.environ.get("QUILL_API_URL", "http://localhost:8000")
    secret = _os.environ.get("AGENT_SHARED_SECRET", "dev-agent-secret-change-me")

    click.echo(
        f"[dev-chat] starting simulate={simulate} poll={poll_interval}s api={api_url}",
        err=True,
    )

    worker = DevChatWorker(
        api_url=api_url,
        agent_secret=secret,
        simulate=simulate,
        poll_interval_s=poll_interval,
    )

    async def _run() -> None:
        await worker.start()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo("[dev-chat] interrupted; shutting down", err=True)
        sys.exit(0)


# ----------------------------------------------------------------------
# `quill-runtime deploy-watch` — auto-deploy watcher (Sprint DC.1)
# ----------------------------------------------------------------------
@main.group("deploy-watch")
def cmd_deploy_watch() -> None:
    """Auto-deploy watcher — redeploys when origin/main gets a new commit."""


@cmd_deploy_watch.command("start")
@click.option(
    "--poll-interval",
    "poll_interval",
    default=None,
    type=float,
    help="Seconds between git fetches. Defaults to REDEPLOY_POLL_INTERVAL_SECONDS or 30.",
)
@click.option(
    "--state-file",
    "state_file",
    default=None,
    help="Override path to last_deployed_sha.txt state file.",
)
def cmd_deploy_watch_start(
    poll_interval: float | None,
    state_file: str | None,
) -> None:
    """Boot the RedeployWatcher daemon (foreground)."""
    from pathlib import Path as _Path

    from runtime.redeploy_watcher import RedeployWatcher, install_signal_handlers

    state_path = _Path(state_file) if state_file else None
    watcher = RedeployWatcher(poll_interval_s=poll_interval, state_file=state_path)
    install_signal_handlers(watcher)

    click.echo(
        f"[deploy-watch] starting poll={poll_interval or 'default'}s",
        err=True,
    )

    async def _run() -> None:
        await watcher.start()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo("[deploy-watch] interrupted; shutting down", err=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
