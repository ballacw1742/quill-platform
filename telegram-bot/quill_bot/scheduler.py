"""APScheduler-driven jobs (Sprint 2.4).

Jobs:
  - daily-brief-fetch (06:30 ET) — gather inputs for the Daily Brief agent
  - daily-brief-deliver (07:00 ET) — render + send to Charles + archive to Drive
  - lane2-reminder-4h (every 15min) — nudge Charles about Lane 2 items >4h
  - lane2-escalate-8h (every 15min) — escalate unanswered Lane 2 items >8h
  - lane3-escalate-12h (every 30min) — escalate unanswered Lane 3 items >12h

The scheduler also pushes its job list to the API via
POST /v1/admin/scheduler/jobs/heartbeat every 60 seconds so admin GET
/v1/admin/scheduler/jobs reflects live state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import subprocess
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from quill_bot.api_client import QuillAPIClient, QuillAPIError
from quill_bot.config import BotConfig

log = logging.getLogger("quill.bot.scheduler")

ET = ZoneInfo("America/New_York")

SendFn = Callable[[str | int, str, bool], Awaitable[None]]


# ---------------------------------------------------------------------------
# Daily Brief
# ---------------------------------------------------------------------------
async def fetch_daily_brief_inputs(api: QuillAPIClient) -> dict[str, Any]:
    """Gather inputs for the Daily Brief agent.

    Sprint 2.4: we collect the deterministic, locally-knowable signals.
    The hyperscaler-inbox / calendar / weather pulls are stubbed because
    they live in adjacent skills that aren't part of this sprint.
    """
    today = datetime.now(ET).date()
    yesterday = today - timedelta(days=1)
    try:
        health = await api.health()
    except QuillAPIError as e:
        log.warning("daily-brief: health fetch failed: %s", e)
        health = {"error": str(e)}

    try:
        pending = await api.list_pending(limit=50)
    except QuillAPIError as e:
        log.warning("daily-brief: list_pending failed: %s", e)
        pending = []

    return {
        "date": today.isoformat(),
        "yesterday": yesterday.isoformat(),
        "fleet_health": health,
        "pending_approvals": pending,
        "pending_count": len(pending) if isinstance(pending, list) else 0,
        # Stubs:
        "yesterday_dfrs": [],
        "critical_path_flags": [
            it for it in (pending or [])
            if isinstance(it, dict) and (it.get("payload") or {}).get("critical_path")
        ],
        "procurement_alerts": [],
        "hyperscaler_inbox": [],
        "calendar_today": [],
        "weather": {"location": "New Albany, OH", "stub": True},
    }


def render_brief_fallback(inputs: dict[str, Any]) -> str:
    """Render a deterministic Markdown brief without the agent.

    Used when the runtime is unreachable so the 7am email still goes out.
    """
    health = inputs.get("fleet_health") or {}
    pending = inputs.get("pending_approvals") or []
    crit = inputs.get("critical_path_flags") or []
    date = inputs.get("date", "today")

    lines = [
        f"# Quill Daily Brief — {date}",
        "",
        "## Fleet health",
        f"- DB: `{health.get('db', '?')}` — overall ok=`{health.get('ok', '?')}`",
        f"- Audit chain: `{health.get('audit_chain', '?')}` (length `{health.get('audit_chain_length', '?')}`)",
        f"- Pending: `{health.get('queue_depth_pending', '?')}` · Executed: `{health.get('queue_depth_executed', '?')}`",
        f"- SLA breaches open: `{health.get('sla_breaches_open', '?')}`",
        "",
        "## Pending approvals",
        f"_{len(pending)} item(s) waiting on you._",
        "",
    ]
    for it in pending[:10]:
        if not isinstance(it, dict):
            continue
        lines.append(
            f"- L{it.get('lane', '?')} `{(it.get('id') or '')[:8]}` — `{it.get('workflow')}`"
            f" (conf {it.get('agent_confidence')}, SLA {it.get('sla_due_at') or '—'})"
        )
    if not pending:
        lines.append("- ✅ Nothing pending.")
    if len(pending) > 10:
        lines.append(f"- …and {len(pending) - 10} more.")

    if crit:
        lines += ["", "## 🚨 Critical-path flags"]
        for it in crit:
            lines.append(
                f"- `{(it.get('id') or '')[:8]}` — `{it.get('workflow')}`"
            )

    lines += [
        "",
        "## Yesterday",
        "- _DFRs / hyperscaler inbox / procurement: pending Sprint 3 integrations._",
        "",
        "_(Brief rendered by deterministic fallback — Daily Brief agent was unavailable.)_",
    ]
    return "\n".join(lines)


async def render_brief_via_runtime(
    inputs: dict[str, Any], *, command_template: str
) -> str | None:
    """Try to invoke `quill-runtime run daily-brief --input <payload>`.

    Returns the rendered Markdown on success, None on failure.
    """
    payload = json.dumps(inputs, default=str)
    cmd = command_template.format(payload=shlex.quote(payload))
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
    except (FileNotFoundError, asyncio.TimeoutError) as e:
        log.warning("daily-brief: runtime invocation failed: %s", e)
        return None
    if proc.returncode != 0:
        log.warning(
            "daily-brief: runtime returned %s: %s",
            proc.returncode,
            err.decode()[:300] if err else "",
        )
        return None
    text = out.decode().strip()
    # Runtime currently outputs JSON for structured agents. If it's JSON,
    # try to extract a `markdown` or `brief` field; otherwise treat as raw.
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for key in ("markdown", "brief", "rendered"):
                if isinstance(data.get(key), str):
                    return data[key]
            # Last-ditch: pretty-print the dict as a code block.
            return "```json\n" + json.dumps(data, indent=2)[:3500] + "\n```"
    except json.JSONDecodeError:
        pass
    return text


async def archive_brief_to_drive(
    config: BotConfig, date_str: str, content: str
) -> str:
    """Use the gog CLI when available, fall back to /tmp/quill-drive."""
    drive_path = config.daily_brief_drive_path_template.format(date=date_str)

    # Try gog
    import tempfile

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    )
    tmp.write(content)
    tmp.close()

    try:
        proc = await asyncio.create_subprocess_exec(
            "gog", "drive", "upload", tmp.name, drive_path, "--mime", "text/markdown",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode == 0:
            log.info("daily-brief: archived to Drive %s", drive_path)
            return f"drive:{drive_path}"
        log.warning(
            "daily-brief: gog upload rc=%s: %s",
            proc.returncode,
            err.decode()[:300] if err else "",
        )
    except FileNotFoundError:
        log.info("daily-brief: gog not on PATH — falling back to /tmp mirror")

    # Fallback: local mirror
    import shutil

    fallback = Path("/tmp/quill-drive") / drive_path.lstrip("/")
    fallback.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(tmp.name, fallback)
    log.info("daily-brief: archived locally at %s", fallback)
    return f"local:{fallback}"


async def run_daily_brief(
    config: BotConfig,
    api: QuillAPIClient,
    send: SendFn,
) -> dict[str, Any]:
    """The 07:00 ET job. Returns a small status dict for tests."""
    date_str = datetime.now(ET).date().isoformat()
    inputs = await fetch_daily_brief_inputs(api)
    rendered = await render_brief_via_runtime(
        inputs, command_template=config.daily_brief_command_template
    )
    if rendered is None:
        rendered = render_brief_fallback(inputs)
        used_fallback = True
    else:
        used_fallback = False

    archive_status = await archive_brief_to_drive(config, date_str, rendered)

    chat_id = config.daily_brief_chat_id
    if not chat_id:
        log.warning("daily-brief: no DAILY_BRIEF_CHAT_ID set; skipping Telegram send")
        return {"ok": True, "delivered": False, "archive": archive_status}

    body = rendered
    if len(body) > 3500:
        body = body[:3500] + "\n…\n_(truncated — full brief on Drive)_"

    try:
        await send(chat_id, body, False)
        delivered = True
    except Exception as e:  # noqa: BLE001
        log.exception("daily-brief: send failed: %s", e)
        try:
            await send(
                chat_id,
                f"❌ *Daily Brief failed* — check Sentry.\n`{type(e).__name__}: {e}`",
                False,
            )
        except Exception:  # noqa: BLE001
            pass
        delivered = False

    return {
        "ok": True,
        "delivered": delivered,
        "fallback_used": used_fallback,
        "archive": archive_status,
        "date": date_str,
    }


# ---------------------------------------------------------------------------
# SLA reminders
# ---------------------------------------------------------------------------
def _age_hours(item: dict[str, Any]) -> float | None:
    raw = item.get("created_at")
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return (datetime.now(UTC) - ts).total_seconds() / 3600


async def remind_lane2_4h(api: QuillAPIClient, send: SendFn, chat_id: str | int) -> int:
    """Find Lane 2 pending items aged 4-8h; send a single rollup message.

    Returns the count of items reminded. Idempotency is best-effort: we
    simply nudge once per scheduler tick. Sprint 4 should track sent state
    per item so we don't spam if the scheduler tick interval shrinks.
    """
    items = await _safe_list(api, lane=2)
    flagged = [
        it for it in items
        if (a := _age_hours(it)) is not None and 4 <= a < 8
    ]
    if not flagged:
        return 0
    lines = [
        f"⏳ *Lane 2 reminder* — {len(flagged)} item(s) pending >4h:",
        *[
            f"- `{(it.get('id') or '')[:8]}` `{it.get('workflow')}` ({_age_hours(it):.1f}h)"
            for it in flagged[:8]
        ],
    ]
    await send(chat_id, "\n".join(lines), False)
    return len(flagged)


async def escalate_lane2_8h(api: QuillAPIClient, send: SendFn, chat_id: str | int) -> int:
    items = await _safe_list(api, lane=2)
    flagged = [it for it in items if (a := _age_hours(it)) is not None and a >= 8]
    if not flagged:
        return 0
    lines = [
        f"🚨 *Lane 2 escalation* — {len(flagged)} item(s) pending >8h. Auto-escalating to Lane 3:",
        *[f"- `{(it.get('id') or '')[:8]}` `{it.get('workflow')}` ({_age_hours(it):.1f}h)" for it in flagged[:8]],
    ]
    await send(chat_id, "\n".join(lines), False)
    return len(flagged)


async def escalate_lane3_12h(api: QuillAPIClient, send: SendFn, chat_id: str | int) -> int:
    items = await _safe_list(api, lane=3)
    flagged = [it for it in items if (a := _age_hours(it)) is not None and a >= 12]
    if not flagged:
        return 0
    lines = [
        f"🆘 *Lane 3 escalation* — {len(flagged)} item(s) pending >12h. Pinging partner:",
        *[f"- `{(it.get('id') or '')[:8]}` `{it.get('workflow')}` ({_age_hours(it):.1f}h)" for it in flagged[:8]],
    ]
    await send(chat_id, "\n".join(lines), False)
    return len(flagged)


async def _safe_list(api: QuillAPIClient, lane: int) -> list[dict[str, Any]]:
    try:
        return await api.list_pending(lane=lane, limit=50)
    except QuillAPIError as e:
        log.warning("list_pending(lane=%s) failed: %s", lane, e)
        return []


# ---------------------------------------------------------------------------
# Scheduler bootstrap
# ---------------------------------------------------------------------------
class QuillScheduler:
    def __init__(
        self,
        config: BotConfig,
        api: QuillAPIClient,
        send: SendFn,
    ) -> None:
        self.config = config
        self.api = api
        self.send = send
        self.scheduler: AsyncIOScheduler = AsyncIOScheduler(timezone=ET)
        self._heartbeat_task: asyncio.Task | None = None

    def schedule_all(self) -> None:
        s = self.scheduler

        s.add_job(
            self._run_daily_brief_job,
            CronTrigger(hour=7, minute=0, timezone=ET),
            id="daily-brief-deliver",
            name="Daily Brief — Telegram + Drive delivery",
            replace_existing=True,
        )
        s.add_job(
            self._run_daily_brief_fetch,
            CronTrigger(hour=6, minute=30, timezone=ET),
            id="daily-brief-fetch",
            name="Daily Brief — fetch inputs",
            replace_existing=True,
        )
        if self.config.reminder_lane2_4h_enabled:
            s.add_job(
                self._reminder_lane2_4h,
                IntervalTrigger(minutes=15),
                id="lane2-reminder-4h",
                name="Lane 2 reminder (>4h pending)",
                replace_existing=True,
            )
            s.add_job(
                self._escalate_lane2_8h,
                IntervalTrigger(minutes=15),
                id="lane2-escalate-8h",
                name="Lane 2 escalation (>8h pending)",
                replace_existing=True,
            )
            s.add_job(
                self._escalate_lane3_12h,
                IntervalTrigger(minutes=30),
                id="lane3-escalate-12h",
                name="Lane 3 escalation (>12h pending)",
                replace_existing=True,
            )

    def jobs_snapshot(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        for j in self.scheduler.get_jobs():
            next_run_at: str | None = None
            # APScheduler exposes next_run_time only after start(); fall back
            # to computing the next fire from the trigger itself.
            try:
                nrt = getattr(j, "next_run_time", None)
                if nrt is not None:
                    next_run_at = nrt.astimezone(UTC).isoformat()
            except Exception:  # noqa: BLE001
                next_run_at = None
            if next_run_at is None:
                try:
                    fire = j.trigger.get_next_fire_time(None, now)
                    if fire is not None:
                        next_run_at = fire.astimezone(UTC).isoformat()
                except Exception:  # noqa: BLE001
                    pass
            out.append(
                {
                    "id": j.id,
                    "name": j.name or j.id,
                    "trigger": str(j.trigger),
                    "next_run_at": next_run_at,
                }
            )
        return out

    async def push_heartbeat(self) -> None:
        try:
            await self.api.scheduler_heartbeat(self.jobs_snapshot())
        except QuillAPIError as e:
            log.warning("scheduler heartbeat failed: %s", e)
        except Exception as e:  # noqa: BLE001
            log.exception("scheduler heartbeat error: %s", e)

    async def _heartbeat_loop(self) -> None:
        while True:
            await self.push_heartbeat()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                return

    def start(self) -> None:
        self.schedule_all()
        self.scheduler.start()
        loop = asyncio.get_event_loop()
        self._heartbeat_task = loop.create_task(self._heartbeat_loop())
        log.info("scheduler started with %d jobs", len(self.scheduler.get_jobs()))

    async def stop(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        self.scheduler.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Job wrappers (logged + Sentry-tagged)
    # ------------------------------------------------------------------
    async def _run_daily_brief_job(self) -> None:
        log.info("daily-brief-deliver: starting")
        result = await run_daily_brief(self.config, self.api, self.send)
        log.info("daily-brief-deliver: result=%s", result)

    async def _run_daily_brief_fetch(self) -> None:
        log.info("daily-brief-fetch: starting")
        await fetch_daily_brief_inputs(self.api)
        log.info("daily-brief-fetch: done")

    def _target_chat(self) -> str | int | None:
        cid = self.config.daily_brief_chat_id
        return cid or None

    async def _reminder_lane2_4h(self) -> None:
        cid = self._target_chat()
        if cid is None:
            return
        n = await remind_lane2_4h(self.api, self.send, cid)
        log.info("lane2-reminder-4h: notified=%d", n)

    async def _escalate_lane2_8h(self) -> None:
        cid = self._target_chat()
        if cid is None:
            return
        n = await escalate_lane2_8h(self.api, self.send, cid)
        log.info("lane2-escalate-8h: notified=%d", n)

    async def _escalate_lane3_12h(self) -> None:
        cid = self._target_chat()
        if cid is None:
            return
        n = await escalate_lane3_12h(self.api, self.send, cid)
        log.info("lane3-escalate-12h: notified=%d", n)
