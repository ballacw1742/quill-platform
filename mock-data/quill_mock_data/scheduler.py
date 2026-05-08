"""APScheduler harness running all feeders + the dispatcher.

Knobs (env-driven):

  MOCK_RFI_PER_HOUR        = 1     (~10/business-day)
  MOCK_SUBMITTAL_PER_HOUR  = 0.5   (~5/business-day)
  MOCK_PROCUREMENT_PER_HR  = 1     (continuous, 24/7)
  MOCK_HYPERSCALER_PER_HR  = 0.2
  MOCK_DFR_TIME            = "07:00" ET
  MOCK_DRY_RUN             = "0" / "1"
"""

from __future__ import annotations

import asyncio
import os
import signal
from datetime import date
from pathlib import Path

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from quill_mock_data.dispatcher import Dispatcher
from quill_mock_data.feeders import dfr as dfr_feeder
from quill_mock_data.feeders import hyperscaler as hyperscaler_feeder
from quill_mock_data.feeders import procurement as procurement_feeder
from quill_mock_data.feeders import rfi as rfi_feeder
from quill_mock_data.feeders import submittal as submittal_feeder

log = structlog.get_logger(__name__)

PID_FILE = Path(__file__).resolve().parent.parent / "_state" / "scheduler.pid"
PID_FILE.parent.mkdir(parents=True, exist_ok=True)


def _is_dry_run() -> bool:
    return os.environ.get("MOCK_DRY_RUN", "0") in ("1", "true", "yes", "on")


def _per_hour(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


async def _drain(events, dispatcher: Dispatcher, label: str) -> None:
    if not events:
        return
    for ev in events:
        result = await dispatcher.dispatch(ev)
        log.info("feeder.dispatch", feeder=label, kind=ev.kind, status=result.get("status"),
                 approval_id=result.get("approval_id"))


async def _rfi_job(dispatcher: Dispatcher) -> None:
    rate = _per_hour("MOCK_RFI_PER_HOUR", 1.0)
    n = 1 if rate >= 1.0 else (1 if asyncio.get_event_loop().time() % 1.0 < rate else 0)
    if n:
        await _drain(rfi_feeder.tick(target_count=n), dispatcher, "rfi")


async def _submittal_job(dispatcher: Dispatcher) -> None:
    rate = _per_hour("MOCK_SUBMITTAL_PER_HOUR", 0.5)
    n = 1 if (rate >= 1.0 or (asyncio.get_event_loop().time() % 1.0) < rate) else 0
    if n:
        await _drain(submittal_feeder.tick(target_count=n), dispatcher, "submittal")


async def _procurement_job(dispatcher: Dispatcher) -> None:
    rate = _per_hour("MOCK_PROCUREMENT_PER_HOUR", 1.0)
    n = max(1, int(round(rate)))
    await _drain(procurement_feeder.tick(target_count=n), dispatcher, "procurement")


async def _hyperscaler_job(dispatcher: Dispatcher) -> None:
    rate = _per_hour("MOCK_HYPERSCALER_PER_HOUR", 0.2)
    if (asyncio.get_event_loop().time() % 1.0) < rate:
        await _drain(hyperscaler_feeder.tick(target_count=1), dispatcher, "hyperscaler")


async def _dfr_job(dispatcher: Dispatcher) -> None:
    await _drain(dfr_feeder.tick(report_date=date.today()), dispatcher, "dfr")


async def _heartbeat(dispatcher: Dispatcher) -> None:
    log.info("scheduler.heartbeat", stats=dict(dispatcher.stats))


async def run_forever(*, fast: bool = False) -> None:
    """Run feeders forever. `fast=True` accelerates schedules for demos/tests."""
    PID_FILE.write_text(str(os.getpid()))
    dispatcher = Dispatcher(dry_run=_is_dry_run())
    await dispatcher.__aenter__()

    sched = AsyncIOScheduler(timezone="America/New_York")

    if fast:
        # 5-minute compressed mode for stress / demos.
        sched.add_job(_rfi_job, IntervalTrigger(seconds=15), args=[dispatcher], id="rfi")
        sched.add_job(_submittal_job, IntervalTrigger(seconds=25), args=[dispatcher], id="submittal")
        sched.add_job(_procurement_job, IntervalTrigger(seconds=20), args=[dispatcher], id="procurement")
        sched.add_job(_hyperscaler_job, IntervalTrigger(seconds=45), args=[dispatcher], id="hyperscaler")
        sched.add_job(_dfr_job, IntervalTrigger(seconds=120), args=[dispatcher], id="dfr")
    else:
        # Realistic-rate mode.
        sched.add_job(_rfi_job, IntervalTrigger(minutes=45), args=[dispatcher], id="rfi")
        sched.add_job(_submittal_job, IntervalTrigger(minutes=90), args=[dispatcher], id="submittal")
        sched.add_job(_procurement_job, IntervalTrigger(minutes=60), args=[dispatcher], id="procurement")
        sched.add_job(_hyperscaler_job, IntervalTrigger(minutes=180), args=[dispatcher], id="hyperscaler")
        sched.add_job(_dfr_job, CronTrigger(hour=7, minute=0), args=[dispatcher], id="dfr")

    sched.add_job(_heartbeat, IntervalTrigger(minutes=1 if not fast else 1),
                  args=[dispatcher], id="heartbeat")

    sched.start()
    log.info("scheduler.started", fast=fast, dry_run=_is_dry_run(), pid=os.getpid())

    stop = asyncio.Event()

    def _handle_signal(*_: object) -> None:
        log.info("scheduler.signal_received")
        stop.set()

    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, _handle_signal)
        loop.add_signal_handler(signal.SIGTERM, _handle_signal)
    except (NotImplementedError, RuntimeError):
        pass  # Windows / unusual platforms

    # Run an immediate kick for visibility.
    await _rfi_job(dispatcher)
    await _procurement_job(dispatcher)

    try:
        await stop.wait()
    finally:
        sched.shutdown(wait=False)
        await dispatcher.__aexit__(None, None, None)
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except OSError:
                pass
        log.info("scheduler.stopped", final_stats=dict(dispatcher.stats))


def stop_running() -> bool:
    """Signal a running scheduler PID. Returns True if a process was signaled."""
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
    except ValueError:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        return False


def is_running() -> tuple[bool, int | None]:
    if not PID_FILE.exists():
        return False, None
    try:
        pid = int(PID_FILE.read_text().strip())
    except ValueError:
        return False, None
    try:
        os.kill(pid, 0)
        return True, pid
    except ProcessLookupError:
        return False, pid
    except PermissionError:
        return True, pid
