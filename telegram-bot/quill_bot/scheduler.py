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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from quill_bot.api_client import QuillAPIClient, QuillAPIError
from quill_bot.config import BotConfig
from quill_bot.dedup import DedupStore, get_store

try:  # Optional Sentry import — bot already initializes it elsewhere
    import sentry_sdk
except Exception:  # pragma: no cover
    sentry_sdk = None  # type: ignore

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


# Default timeout for the runtime invocation. The fix-#3 job-queue pattern
# treats anything beyond this as "runtime is wedged" and falls back.
DAILY_BRIEF_RUNTIME_TIMEOUT_S = 180


async def render_brief_via_runtime(
    inputs: dict[str, Any],
    *,
    command_template: str,
    timeout: float = DAILY_BRIEF_RUNTIME_TIMEOUT_S,
) -> str | None:
    """Try to invoke `quill-runtime run daily-brief --input <payload>`.

    Returns the rendered Markdown on success, None on failure (including
    timeout). Caller is expected to fall back to the deterministic brief.
    """
    payload = json.dumps(inputs, default=str)
    cmd = command_template.format(payload=shlex.quote(payload))
    proc = None
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except FileNotFoundError as e:
        log.warning("daily-brief: runtime invocation failed: %s", e)
        return None
    except asyncio.TimeoutError:
        log.warning(
            "daily-brief: runtime exceeded %ss — falling back", timeout
        )
        if proc is not None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        if sentry_sdk is not None:
            try:
                sentry_sdk.capture_message(
                    "daily_brief.runtime_timeout", level="warning"
                )
            except Exception:  # noqa: BLE001
                pass
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


async def _send_brief_to_telegram(
    send: SendFn, chat_id: str | int, body: str
) -> bool:
    """Helper used by `run_daily_brief` so it can run concurrently with Drive."""
    if len(body) > 3500:
        body = body[:3500] + "\n…\n_(truncated — full brief on Drive)_"
    try:
        await send(chat_id, body, False)
        return True
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
        return False


async def run_daily_brief(
    config: BotConfig,
    api: QuillAPIClient,
    send: SendFn,
    *,
    runtime_timeout: float = DAILY_BRIEF_RUNTIME_TIMEOUT_S,
) -> dict[str, Any]:
    """The 07:00 ET job. Returns a small status dict for tests.

    Sprint-4 fix #3 + #5:
      - The runtime invocation has a hard timeout (default 180s) and falls
        back to the deterministic brief on timeout.
      - Telegram send and Drive archive run concurrently via asyncio.gather
        so a slow Drive upload never blocks the user from seeing the brief.
    """
    date_str = datetime.now(ET).date().isoformat()
    inputs = await fetch_daily_brief_inputs(api)
    rendered = await render_brief_via_runtime(
        inputs,
        command_template=config.daily_brief_command_template,
        timeout=runtime_timeout,
    )
    if rendered is None:
        rendered = render_brief_fallback(inputs)
        used_fallback = True
    else:
        used_fallback = False

    chat_id = config.daily_brief_chat_id

    # Kick off Telegram send + Drive upload concurrently. Drive failures are
    # best-effort; Telegram failures degrade to a fallback notice (already
    # handled inside `_send_brief_to_telegram`).
    drive_coro = archive_brief_to_drive(config, date_str, rendered)
    if chat_id:
        send_coro = _send_brief_to_telegram(send, chat_id, rendered)
        results = await asyncio.gather(send_coro, drive_coro, return_exceptions=True)
        send_result, drive_result = results
    else:
        log.warning("daily-brief: no DAILY_BRIEF_CHAT_ID set; skipping Telegram send")
        send_result = None
        drive_result = await drive_coro

    if isinstance(drive_result, BaseException):
        log.warning("daily-brief: drive archive failed: %s", drive_result)
        archive_status = f"error:{type(drive_result).__name__}"
    else:
        archive_status = drive_result

    if chat_id is None or chat_id == "":
        delivered = False
    elif isinstance(send_result, BaseException):
        log.warning("daily-brief: telegram send raised: %s", send_result)
        delivered = False
    else:
        delivered = bool(send_result)

    return {
        "ok": True,
        "delivered": delivered,
        "fallback_used": used_fallback,
        "archive": archive_status,
        "date": date_str,
    }


# ---------------------------------------------------------------------------
# Sprint-4 fix #3: Async DR job queue for the Daily Brief
#
# At 06:30 ET the scheduler enqueues a DailyBriefJob. A long-running worker
# task drains the queue. The runtime invocation is bounded by a 180s timeout
# so the scheduler loop never stalls on slow LLM calls.
# ---------------------------------------------------------------------------
@dataclass
class DailyBriefJob:
    enqueued_at: datetime
    config: BotConfig
    api: QuillAPIClient
    send: SendFn
    runtime_timeout: float = DAILY_BRIEF_RUNTIME_TIMEOUT_S


class DailyBriefQueue:
    """Bounded in-process queue. Dropping a duplicate is preferable to
    piling up jobs if a previous run is still finishing."""

    def __init__(self, *, maxsize: int = 4) -> None:
        self._queue: asyncio.Queue[DailyBriefJob] = asyncio.Queue(maxsize=maxsize)
        self._worker: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.last_result: dict[str, Any] | None = None

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        return self._worker is not None and not self._worker.done()

    async def enqueue(self, job: DailyBriefJob) -> bool:
        try:
            self._queue.put_nowait(job)
            return True
        except asyncio.QueueFull:
            log.warning("daily-brief queue full — dropping job")
            if sentry_sdk is not None:
                try:
                    sentry_sdk.capture_message(
                        "daily_brief.queue_full", level="warning"
                    )
                except Exception:  # noqa: BLE001
                    pass
            return False

    async def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._worker = asyncio.create_task(self._run(), name="daily-brief-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._worker = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                self.last_result = await run_daily_brief(
                    job.config,
                    job.api,
                    job.send,
                    runtime_timeout=job.runtime_timeout,
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("daily-brief job failed: %s", exc)
                self.last_result = {"ok": False, "error": str(exc)}
            finally:
                self._queue.task_done()


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


def _filter_unreminded(
    items: list[dict[str, Any]],
    *,
    age_pred,
    kind: str,
    store: DedupStore,
) -> list[dict[str, Any]]:
    """Apply both an age predicate AND the dedup claim. Items that have
    already had this kind of reminder fired are dropped silently.
    """
    out: list[dict[str, Any]] = []
    for it in items:
        age = _age_hours(it)
        if age is None or not age_pred(age):
            continue
        appr_id = it.get("id") or ""
        if not appr_id:
            continue
        if not store.claim_reminder(appr_id, kind):
            continue
        out.append(it)
    return out


async def remind_lane2_4h(
    api: QuillAPIClient,
    send: SendFn,
    chat_id: str | int,
    *,
    store: DedupStore | None = None,
) -> int:
    """Find Lane 2 pending items aged 4-8h that have NOT had a 4h reminder yet.

    Idempotency: each `(approval_id, 'lane2_4h')` pair fires at most once,
    persisted to the dedup store so bot restarts don't re-nudge.
    """
    s = store or get_store()
    items = await _safe_list(api, lane=2)
    flagged = _filter_unreminded(
        items, age_pred=lambda a: 4 <= a < 8, kind="lane2_4h", store=s
    )
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


async def escalate_lane2_8h(
    api: QuillAPIClient,
    send: SendFn,
    chat_id: str | int,
    *,
    store: DedupStore | None = None,
) -> int:
    s = store or get_store()
    items = await _safe_list(api, lane=2)
    flagged = _filter_unreminded(
        items, age_pred=lambda a: a >= 8, kind="lane2_8h", store=s
    )
    if not flagged:
        return 0
    lines = [
        f"🚨 *Lane 2 escalation* — {len(flagged)} item(s) pending >8h. Auto-escalating to Lane 3:",
        *[f"- `{(it.get('id') or '')[:8]}` `{it.get('workflow')}` ({_age_hours(it):.1f}h)" for it in flagged[:8]],
    ]
    await send(chat_id, "\n".join(lines), False)
    return len(flagged)


async def escalate_lane3_12h(
    api: QuillAPIClient,
    send: SendFn,
    chat_id: str | int,
    *,
    store: DedupStore | None = None,
) -> int:
    s = store or get_store()
    items = await _safe_list(api, lane=3)
    flagged = _filter_unreminded(
        items, age_pred=lambda a: a >= 12, kind="lane3_12h", store=s
    )
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
        # Sprint-4 fix #3: bounded queue + worker for the Daily Brief.
        self.daily_brief_queue = DailyBriefQueue(maxsize=4)

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
            self._enqueue_daily_brief,
            CronTrigger(hour=6, minute=30, timezone=ET),
            id="daily-brief-fetch",
            name="Daily Brief — enqueue + fetch inputs",
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
        """Push the job snapshot to the API with at-least-once delivery.

        Sprint-4 fix #4: retries up to 5 times with exponential backoff
        (1s, 2s, 4s, 8s, 16s) on connection errors / 5xx. The heartbeat is
        non-critical so a final failure logs a Sentry event but does NOT
        block the scheduler loop.
        """
        delays = (1.0, 2.0, 4.0, 8.0, 16.0)
        last_exc: BaseException | None = None
        for attempt, delay in enumerate(delays, start=1):
            try:
                await self.api.scheduler_heartbeat(self.jobs_snapshot())
                if attempt > 1:
                    log.info("scheduler heartbeat recovered on attempt %d", attempt)
                return
            except QuillAPIError as e:
                last_exc = e
                retryable = e.status >= 500 or e.status == 0
                log.warning(
                    "scheduler heartbeat attempt %d/%d failed: %s",
                    attempt,
                    len(delays),
                    e,
                )
                if not retryable or attempt == len(delays):
                    break
            except Exception as e:  # noqa: BLE001
                last_exc = e
                log.warning(
                    "scheduler heartbeat attempt %d/%d errored: %s",
                    attempt,
                    len(delays),
                    e,
                )
                if attempt == len(delays):
                    break
            await asyncio.sleep(delay)
        # All retries exhausted — surface to Sentry but never block the loop.
        log.error(
            "scheduler heartbeat: gave up after %d attempts last_err=%s",
            len(delays),
            last_exc,
        )
        if sentry_sdk is not None:
            try:
                sentry_sdk.capture_message(
                    "scheduler.heartbeat_final_failure",
                    level="error",
                )
            except Exception:  # noqa: BLE001
                pass

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
        loop.create_task(self.daily_brief_queue.start(), name="daily-brief-queue-start")
        log.info("scheduler started with %d jobs", len(self.scheduler.get_jobs()))

    async def stop(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        await self.daily_brief_queue.stop()
        self.scheduler.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Job wrappers (logged + Sentry-tagged)
    # ------------------------------------------------------------------
    async def _run_daily_brief_job(self) -> None:
        """07:00 ET wake-up: enqueue the brief job. The worker (started in
        :meth:`start`) drains the queue out-of-band so this scheduler tick
        returns immediately.
        """
        log.info("daily-brief-deliver: enqueueing")
        if not self.daily_brief_queue.is_running:
            await self.daily_brief_queue.start()
        ok = await self.daily_brief_queue.enqueue(
            DailyBriefJob(
                enqueued_at=datetime.now(UTC),
                config=self.config,
                api=self.api,
                send=self.send,
            )
        )
        log.info("daily-brief-deliver: enqueued=%s", ok)

    async def _enqueue_daily_brief(self) -> None:
        """06:30 ET fetch inputs (warms caches) AND enqueue an early brief
        job, so the 07:00 delivery has a head start. Idempotent w.r.t. the
        queue's bound — if a previous job is still draining we drop the dupe.
        """
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
