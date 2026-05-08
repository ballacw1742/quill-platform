"""quill-mock CLI."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import click

from quill_mock_data import __version__
from quill_mock_data.dispatcher import DISPATCH_LOG, dispatch_many
from quill_mock_data.feeders import dfr as dfr_feeder
from quill_mock_data.feeders import hyperscaler as hyperscaler_feeder
from quill_mock_data.feeders import procurement as procurement_feeder
from quill_mock_data.feeders import rfi as rfi_feeder
from quill_mock_data.feeders import submittal as submittal_feeder
from quill_mock_data.scheduler import is_running, run_forever, stop_running
from quill_mock_data.seed import STATE_DIR, load_state, write_state


FEEDER_MAP = {
    "rfi": rfi_feeder,
    "submittal": submittal_feeder,
    "dfr": dfr_feeder,
    "procurement": procurement_feeder,
    "hyperscaler": hyperscaler_feeder,
}


@click.group()
@click.version_option(__version__, prog_name="quill-mock")
def cli() -> None:
    """Quill mock-data CLI — synthetic feeds for QPB1."""


@cli.command()
def bootstrap() -> None:
    """One-shot: write the spec corpus, subs, POs, and IMS XER under _state/."""
    paths = write_state()
    click.echo(json.dumps({k: str(v) for k, v in paths.items()}, indent=2))
    state = load_state()
    click.echo(
        f"\n  spec_sections={len(state['spec_sections'])} "
        f"subs={len(state['subcontractors'])} "
        f"long_lead_pos={len(state['long_lead_pos'])}"
    )
    click.echo(f"  state dir: {STATE_DIR}")


@cli.command()
@click.option("--fast/--realistic", default=False,
              help="Fast mode for demos: feeders fire every 15-120s instead of 45-180min.")
@click.option("--dry-run/--live", default=False,
              help="Build payloads but skip the API POST (useful for offline dev).")
def start(fast: bool, dry_run: bool) -> None:
    """Run the feeders + dispatcher in the foreground."""
    running, pid = is_running()
    if running:
        click.echo(f"already running (pid={pid})", err=True)
        sys.exit(2)
    if dry_run:
        import os
        os.environ["MOCK_DRY_RUN"] = "1"
    try:
        asyncio.run(run_forever(fast=fast))
    except KeyboardInterrupt:
        click.echo("interrupted")


@cli.command()
def stop() -> None:
    """Signal a running scheduler to shut down (best-effort)."""
    if stop_running():
        click.echo("SIGTERM sent.")
    else:
        click.echo("no running scheduler found.", err=True)
        sys.exit(1)


@cli.command()
def status() -> None:
    """Show scheduler PID and recent dispatch log entries."""
    running, pid = is_running()
    click.echo(json.dumps({
        "running": running,
        "pid": pid,
        "state_dir": str(STATE_DIR),
        "dispatch_log": str(DISPATCH_LOG),
        "dispatch_log_lines": _line_count(DISPATCH_LOG),
    }, indent=2))


@cli.command()
@click.option("--feeder", type=click.Choice(list(FEEDER_MAP)), required=True)
@click.option("--count", default=1, show_default=True, help="How many events to emit.")
@click.option("--dry-run/--live", default=False)
@click.option("--seed", type=int, default=None)
def tick(feeder: str, count: int, dry_run: bool, seed: int | None) -> None:
    """Emit N events from one feeder, dispatch them, print results."""
    mod = FEEDER_MAP[feeder]
    if feeder == "dfr":
        events = mod.tick(report_date=date.today(), seed=seed)
    else:
        events = mod.tick(target_count=count, seed=seed)
    out = asyncio.run(dispatch_many(events, dry_run=dry_run))
    click.echo(json.dumps({
        "feeder": feeder,
        "emitted": len(events),
        "results": out,
    }, indent=2, default=str))


def _line_count(p: Path) -> int:
    if not p.exists():
        return 0
    with p.open() as f:
        return sum(1 for _ in f)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
