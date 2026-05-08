#!/usr/bin/env python3
"""Daily Brief pipeline (Sprint 3).

The Telegram scheduler shells into this at 06:30 ET. It assembles the
Daily Brief agent's input from real signals + the mock-data layer, runs
the agent (or a deterministic fallback), and prints the rendered Markdown
to stdout for the bot to deliver.

Inputs:
  - GET /v1/admin/health                      (fleet + queue depth)
  - GET /v1/approvals?status=pending          (live queue)
  - GET /v1/audit/recent                      (last 24h)
  - mock-data/_state/dispatch.log              (yesterday's DFRs, procurement)
  - mock-data/calendar.json                    (Charles's calendar — mocked)
  - wttr.in/Westerville+OH                     (weather; mocked on failure)

Output: Markdown to stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MOCK_STATE = REPO_ROOT / "mock-data" / "_state"
CALENDAR_JSON = REPO_ROOT / "mock-data" / "calendar.json"


def _api_url() -> str:
    return os.environ.get("QUILL_API_URL", "http://localhost:8000").rstrip("/")


def _agent_secret() -> str:
    return os.environ.get("AGENT_SHARED_SECRET", "dev-agent-secret-change-me")


# ---------------------------------------------------------------------------
# Input collection
# ---------------------------------------------------------------------------
async def fetch_api_health(client: httpx.AsyncClient) -> dict[str, Any]:
    try:
        r = await client.get("/v1/admin/health",
                             headers={"X-Admin": _agent_secret()},
                             timeout=5.0)
        if r.status_code < 300:
            return r.json()
    except httpx.HTTPError:
        pass
    return {"queue_depth_pending": 0, "audit_chain": "unknown", "fleet": []}


async def fetch_pending_approvals(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        r = await client.get("/v1/approvals", params={"status": "pending", "limit": 200},
                             headers={"X-Agent-Secret": _agent_secret()},
                             timeout=8.0)
        if r.status_code < 300:
            items = r.json().get("items", [])
    except httpx.HTTPError:
        pass
    return items


async def fetch_audit_recent(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    try:
        r = await client.get("/v1/audit/recent", params={"limit": 200},
                             headers={"X-Agent-Secret": _agent_secret()},
                             timeout=8.0)
        if r.status_code < 300:
            payload = r.json()
            return payload.get("items", payload) if isinstance(payload, dict) else payload
    except httpx.HTTPError:
        pass
    return []


def read_dispatch_log_yesterday() -> list[dict[str, Any]]:
    path = MOCK_STATE / "dispatch.log"
    if not path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    out: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if ts >= cutoff:
                out.append(rec)
    return out


def read_calendar_today() -> list[dict[str, Any]]:
    if not CALENDAR_JSON.exists():
        return []
    data = json.loads(CALENDAR_JSON.read_text())
    today = date.today().isoformat()
    return [e for e in data.get("events", []) if e.get("date") == today]


async def fetch_weather() -> dict[str, Any]:
    fallback = {
        "location": "Westerville, OH",
        "high_f": 68, "low_f": 50, "conditions": "partly cloudy",
        "wind_mph": 8, "source": "fake",
    }
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get("https://wttr.in/Westerville+OH", params={"format": "j1"})
        if r.status_code < 300:
            j = r.json()
            current = j.get("current_condition", [{}])[0]
            today = j.get("weather", [{}])[0]
            return {
                "location": "Westerville, OH",
                "high_f": int(today.get("maxtempF", fallback["high_f"])),
                "low_f": int(today.get("mintempF", fallback["low_f"])),
                "conditions": current.get("weatherDesc", [{"value": fallback["conditions"]}])[0]["value"],
                "wind_mph": int(current.get("windspeedMiles", fallback["wind_mph"])),
                "source": "wttr.in",
            }
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        pass
    return fallback


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def _bucket_pending_by_lane(items: list[dict[str, Any]]) -> dict[int, int]:
    out = {1: 0, 2: 0, 3: 0}
    for it in items:
        lane = it.get("lane")
        if isinstance(lane, int):
            out[lane] = out.get(lane, 0) + 1
    return out


def _yesterday_dfr_rollup(dispatches: list[dict[str, Any]]) -> dict[str, Any]:
    dfrs = [d for d in dispatches if d.get("kind") == "dfr.new"]
    return {
        "dfr_count": len(dfrs),
        "by_building": sorted({d.get("summary", "").split()[0] for d in dfrs}),
        "samples": [d.get("summary") for d in dfrs[:4]],
    }


def _critical_path_flags(dispatches: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for d in dispatches:
        if d.get("kind") == "procurement.update" and d.get("priority") == "critical_path":
            out.append(d.get("summary", "(unspecified)"))
    return out


def _procurement_alerts(dispatches: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for d in dispatches:
        if d.get("kind") == "procurement.update" and d.get("priority") in ("high", "critical_path"):
            out.append(d.get("summary", "(unspecified)"))
    return out


def _hyperscaler_inbox_count(dispatches: list[dict[str, Any]]) -> int:
    return sum(1 for d in dispatches if d.get("kind") == "hyperscaler.inbound")


# ---------------------------------------------------------------------------
# Renderer (deterministic — runtime-agnostic; agent path is a wrapper)
# ---------------------------------------------------------------------------
def render_brief(brief_input: dict[str, Any]) -> str:
    today = date.today()
    h = brief_input["health"]
    lanes = brief_input["pending_by_lane"]
    dfr = brief_input["dfr_rollup"]
    cp_flags = brief_input["critical_path_flags"]
    procurement = brief_input["procurement_alerts"]
    inbox = brief_input["hyperscaler_inbox"]
    cal = brief_input["calendar_today"]
    weather = brief_input["weather"]
    fleet = h.get("fleet") or []
    suspended = [f for f in fleet if f.get("status") == "suspended"]

    top_of_mind: list[str] = []
    if cp_flags:
        top_of_mind.append(f"🚨 {len(cp_flags)} critical-path procurement flag(s) overnight.")
    if lanes.get(3, 0):
        top_of_mind.append(f"⏳ {lanes[3]} dual-approval item(s) pending — partner needed.")
    if lanes.get(2, 0) >= 8:
        top_of_mind.append(f"📬 Queue depth (single-approve): {lanes[2]} — consider a triage block.")
    if suspended:
        top_of_mind.append(f"⚠ {len(suspended)} agent(s) suspended.")
    if inbox > 3:
        top_of_mind.append(f"📥 {inbox} owner-side inbound item(s) overnight.")
    if not top_of_mind:
        top_of_mind.append("All clear — green across the board.")

    md: list[str] = []
    md.append(f"# Quill Daily Brief — {today.isoformat()} (QPB1)")
    md.append("")
    md.append("## Top of mind")
    for t in top_of_mind:
        md.append(f"- {t}")
    md.append("")

    md.append("## Quill fleet")
    md.append(f"- Queue depth (pending): **{h.get('queue_depth_pending', 0)}**")
    md.append(f"- Lane 1 auto: {lanes.get(1,0)} | Lane 2 single: {lanes.get(2,0)} | Lane 3 dual: {lanes.get(3,0)}")
    md.append(f"- Audit chain: {h.get('audit_chain', 'unknown')}")
    md.append(f"- Agents healthy: {sum(1 for f in fleet if f.get('status') != 'suspended')} / {len(fleet) or 0}")
    md.append("")

    md.append("## Yesterday's field")
    md.append(f"- DFRs received: {dfr['dfr_count']} ({', '.join(dfr['by_building']) or 'none'})")
    for s in dfr["samples"]:
        md.append(f"  - {s}")
    md.append("")

    md.append("## Procurement watch")
    if procurement:
        for p in procurement[:8]:
            md.append(f"- {p}")
    else:
        md.append("- No new high-priority procurement alerts.")
    md.append("")

    md.append("## Hyperscaler inbox")
    md.append(f"- {inbox} item(s) overnight needing classification.")
    md.append("")

    md.append("## Today's calendar")
    if cal:
        for ev in sorted(cal, key=lambda e: e.get("time", "00:00")):
            md.append(f"- {ev.get('time','')}  {ev['title']} ({ev.get('duration_min','?')}m)")
    else:
        md.append("- (no events on file)")
    md.append("")

    md.append("## Weather — Westerville, OH")
    md.append(f"- {weather['conditions'].title()}, {weather['low_f']}–{weather['high_f']}°F, wind {weather['wind_mph']} mph ({weather['source']})")
    md.append("")
    md.append("---")
    md.append(f"*Generated {datetime.now(timezone.utc).isoformat()} from real synthetic data.*")
    return "\n".join(md)


# ---------------------------------------------------------------------------
# Optional: run the daily-brief Agent through the runtime
# ---------------------------------------------------------------------------
async def try_run_agent(brief_input: dict[str, Any]) -> str | None:
    """If runtime + ANTHROPIC_API_KEY are set, drive the daily-brief agent.

    Returns the rendered markdown on success, None otherwise (caller falls
    back to render_brief()).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        from runtime.agent import Agent  # noqa: WPS433
        from runtime.config import get_config  # noqa: WPS433
    except Exception:
        return None
    try:
        cfg = get_config()
        agent = Agent("daily-brief", config=cfg)
        run = await agent.run(brief_input, submit_to_queue=False, workflow="daily-brief.compose")
        if run.output and isinstance(run.output, dict):
            return run.output.get("markdown") or run.output.get("brief_md")
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def assemble_input() -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=_api_url(), timeout=8.0) as client:
        health, pending, audit = await asyncio.gather(
            fetch_api_health(client),
            fetch_pending_approvals(client),
            fetch_audit_recent(client),
        )
    dispatches = read_dispatch_log_yesterday()
    weather = await fetch_weather()
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "health": health,
        "pending_count": len(pending),
        "pending_by_lane": _bucket_pending_by_lane(pending),
        "audit_recent_count": len(audit),
        "dfr_rollup": _yesterday_dfr_rollup(dispatches),
        "critical_path_flags": _critical_path_flags(dispatches),
        "procurement_alerts": _procurement_alerts(dispatches),
        "hyperscaler_inbox": _hyperscaler_inbox_count(dispatches),
        "calendar_today": read_calendar_today(),
        "weather": weather,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Quill Daily Brief pipeline")
    parser.add_argument("--json", action="store_true",
                        help="Emit the assembled input as JSON instead of rendered markdown.")
    parser.add_argument("--use-agent", action="store_true",
                        help="Try to run the daily-brief agent via runtime.")
    args = parser.parse_args()

    brief_input = asyncio.run(assemble_input())
    if args.json:
        print(json.dumps(brief_input, indent=2, default=str))
        return 0

    rendered: str | None = None
    if args.use_agent:
        rendered = asyncio.run(try_run_agent(brief_input))
    if rendered is None:
        rendered = render_brief(brief_input)
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
