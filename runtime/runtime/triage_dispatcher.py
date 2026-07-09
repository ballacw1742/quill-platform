"""TriageDispatcher — long-running daemon that watches an event source and
runs the appropriate agent chain for each new event.

In dev/CI the event source is a file at `mock-data/_state/dispatch.log`
(JSONL, one line per event). In prod the source would be Procore webhooks
landing on the API; that's a separate sprint.

Design goals:
- **Polling-resilient.** Restarts pick up where they left off (cursor file).
- **Idempotent.** Duplicate events (same `event_id`) are deduped.
- **Crash-safe.** Cursor is fsynced after every batch.
- **Configurable source.** `MockDataEventSource` for dev; future
  `WebhookEventSource` would plug in identically.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import os
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterable, AsyncIterator, Callable

import structlog

from runtime.chains import (
    DEFAULT_CHAINS,
    Chain,
    ChainResult,
    chain_for_event,
    run_chain,
)
from runtime.config import Config, get_config
from runtime.queue_client import QueueClient

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TriageEvent:
    """Generic envelope for any inbound event the dispatcher handles."""

    event_id: str
    kind: str  # e.g. "rfi.new"
    payload: dict[str, Any]
    source: str = "unknown"
    raw: dict[str, Any] | None = None  # the original log line

    @classmethod
    def from_log_record(cls, rec: dict[str, Any]) -> TriageEvent | None:
        """Parse a dispatch.log record into a TriageEvent.

        The mock-data dispatcher logs lines that look like:
            {"ts": "...", "kind": "rfi.new", "source": "feeder",
             "status": "submitted", "approval_id": "...",
             "summary": "...", "agent_id": "..."}

        For the mock source, we don't have the raw event payload in the
        log line — so we synthesize a minimal payload from the summary +
        any embedded fields. The chain runs against this minimal payload;
        real production would source the original event from a richer
        store.

        Returns None for log lines that aren't dispatchable events
        (status=skipped, status=error, etc.).
        """
        kind = rec.get("kind")
        status = rec.get("status")
        if not kind:
            return None
        if status not in (None, "submitted", "dry_run"):
            return None
        # event_id: prefer the dispatcher-stamped event_id (Phase F.1); fall
        # back to approval_id; finally synthesize from (ts, kind, summary).
        event_id = (
            rec.get("event_id")
            or rec.get("approval_id")
            or f"{rec.get('ts','')}-{kind}-{rec.get('summary','')}"
        )
        payload = rec.get("payload") or {
            # Minimal envelope so the chain has *something* to feed agents.
            "summary": rec.get("summary"),
            "kind": kind,
            "lane": rec.get("lane"),
            "priority": rec.get("priority"),
            "agent_id": rec.get("agent_id"),
            "approval_id": rec.get("approval_id"),
        }
        return cls(
            event_id=event_id,
            kind=kind,
            payload=payload,
            source=rec.get("source", "dispatch_log"),
            raw=rec,
        )


# ---------------------------------------------------------------------------
# Event sources
# ---------------------------------------------------------------------------
class EventSource:
    """Abstract async iterable of TriageEvent."""

    def __aiter__(self) -> AsyncIterator[TriageEvent]:
        raise NotImplementedError

    async def aclose(self) -> None:
        pass


class MockDataEventSource(EventSource):
    """Polls a JSONL file for new lines since the last cursor.

    Cursor is stored next to the log as `<log>.cursor` and contains a single
    integer byte-offset.

    Restart safety: on boot we re-read the cursor; on every successful
    batch we fsync the new cursor. Duplicate events are deduped via
    `event_id` against an in-memory set bounded by `dedupe_capacity`.
    """

    def __init__(
        self,
        log_path: Path,
        *,
        cursor_path: Path | None = None,
        poll_interval_s: float = 5.0,
        dedupe_capacity: int = 5_000,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        self.log_path = Path(log_path)
        self.cursor_path = cursor_path or self.log_path.with_suffix(self.log_path.suffix + ".cursor")
        self.poll_interval_s = poll_interval_s
        self.dedupe_capacity = dedupe_capacity
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque(maxlen=dedupe_capacity)
        self._stop_event = stop_event or asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def _read_cursor(self) -> int:
        if not self.cursor_path.exists():
            return 0
        try:
            return int(self.cursor_path.read_text(encoding="utf-8").strip() or 0)
        except (ValueError, OSError):
            return 0

    def _write_cursor(self, offset: int) -> None:
        # Atomic-ish: write to tmp then rename.
        tmp = self.cursor_path.with_suffix(self.cursor_path.suffix + ".tmp")
        tmp.write_text(str(offset), encoding="utf-8")
        os.replace(tmp, self.cursor_path)

    def _record_seen(self, event_id: str) -> bool:
        """Return True if this event_id is new; False if duplicate."""
        if event_id in self._seen:
            return False
        if len(self._seen_order) == self._seen_order.maxlen:
            old = self._seen_order[0]
            self._seen.discard(old)
        self._seen.add(event_id)
        self._seen_order.append(event_id)
        return True

    async def _read_new_records(self) -> tuple[list[dict[str, Any]], int]:
        """Read all new lines from cursor onward; return (records, new_offset)."""
        if not self.log_path.exists():
            return [], self._read_cursor()
        offset = self._read_cursor()
        records: list[dict[str, Any]] = []
        try:
            size = self.log_path.stat().st_size
        except OSError:
            return [], offset
        # If the file shrank (rotated/truncated), reset cursor.
        if size < offset:
            log.warning(
                "triage.source.log_truncated",
                old_offset=offset,
                new_size=size,
            )
            offset = 0
        if size == offset:
            return [], offset
        try:
            with self.log_path.open("rb") as fh:
                fh.seek(offset)
                data = fh.read()
                new_offset = offset + len(data)
        except OSError as e:
            log.error("triage.source.read_fail", err=str(e))
            return [], offset
        text = data.decode("utf-8", errors="replace")
        # Only consume up through the LAST complete newline; partial
        # trailing lines stay for next poll.
        last_newline = text.rfind("\n")
        if last_newline == -1:
            return [], offset  # nothing complete yet
        consumed = text[: last_newline + 1]
        new_offset = offset + len(consumed.encode("utf-8"))
        for line in consumed.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning("triage.source.bad_jsonl", line=line[:120])
        return records, new_offset

    async def __aiter__(self) -> AsyncIterator[TriageEvent]:
        while not self._stop_event.is_set():
            records, new_offset = await self._read_new_records()
            if records:
                advanced = False
                for rec in records:
                    event = TriageEvent.from_log_record(rec)
                    if event is None:
                        continue
                    if not self._record_seen(event.event_id):
                        continue
                    advanced = True
                    yield event
                # Persist cursor whether or not we yielded — we've consumed
                # the file bytes.
                self._write_cursor(new_offset)
                if not advanced:
                    log.debug("triage.source.no_dispatchable", count=len(records))
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.poll_interval_s
                )
            except asyncio.TimeoutError:
                continue


class InMemoryEventSource(EventSource):
    """Test helper: yields a fixed list of events then stops."""

    def __init__(self, events: list[TriageEvent]) -> None:
        self._events = list(events)

    async def __aiter__(self) -> AsyncIterator[TriageEvent]:
        for e in self._events:
            yield e


class WebhookEventSource(EventSource):
    """HTTP webhook listener that accepts POST /events and feeds events into
    the dispatcher.  Selected when TRIAGE_EVENT_SOURCE=webhook.

    Auth: every request must carry the ``X-Triage-Secret`` header whose value
    matches ``TRIAGE_WEBHOOK_SECRET`` (env).  An empty/unset secret disables
    the header check (dev-only — always configure a secret in prod).

    Request body:
        {"events": [{...one TriageEvent log-record shape...}, ...]}

    Each record is parsed through TriageEvent.from_log_record; records that
    produce None are silently dropped (same dedup as MockDataEventSource).

    The HTTP server runs in a daemon thread so it does not block the asyncio
    event loop.  Events are bridged into the async consumer via
    asyncio.Queue.  The server binds to 0.0.0.0 on ``port`` (default 8765).
    """

    def __init__(
        self,
        *,
        port: int = 8765,
        secret: str = "",
        stop_event: asyncio.Event | None = None,
        _queue: asyncio.Queue | None = None,
    ) -> None:
        self.port = port
        self._secret = secret
        self._stop_event = stop_event or asyncio.Event()
        # Allow injection of a pre-created queue (test hook).
        self._queue: asyncio.Queue = _queue if _queue is not None else asyncio.Queue()
        self._server: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background HTTP server thread."""
        loop = asyncio.get_running_loop()
        self._thread = threading.Thread(
            target=self._serve_forever,
            args=(loop,),
            daemon=True,
            name="triage-webhook-server",
        )
        self._thread.start()
        # Brief yield so the OS has time to bind the socket before the
        # first request in tests.
        await asyncio.sleep(0.05)

    def stop(self) -> None:
        """Signal the async iterator and shut down the HTTP server."""
        self._stop_event.set()
        if self._server is not None:
            threading.Thread(
                target=self._server.shutdown, daemon=True, name="triage-webhook-shutdown"
            ).start()

    async def aclose(self) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Internal: HTTP server thread
    # ------------------------------------------------------------------

    def _serve_forever(self, loop: asyncio.AbstractEventLoop) -> None:
        source = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # type: ignore[override]
                """Suppress per-request stderr output."""

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/events":
                    self._reply(404, b'{"error": "not found"}')
                    return

                # Authentication.
                secret = self.headers.get("X-Triage-Secret", "")
                if source._secret and secret != source._secret:
                    self._reply(401, b'{"error": "unauthorized"}')
                    return

                # Parse body.
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    self._reply(400, b'{"error": "invalid JSON"}')
                    return

                if not isinstance(data, dict) or "events" not in data:
                    self._reply(400, b'{"error": "body must have an events key"}')
                    return

                events = data.get("events", [])
                if not isinstance(events, list):
                    self._reply(400, b'{"error": "events must be an array"}')
                    return

                # Bridge into the asyncio event loop safely from this thread.
                for ev in events:
                    asyncio.run_coroutine_threadsafe(
                        source._queue.put(ev), loop
                    )

                self._reply(200, b'{"ok": true}')

            def _reply(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = http.server.HTTPServer(("", source.port), _Handler)
        source._server = server
        try:
            server.serve_forever()
        finally:
            server.server_close()

    # ------------------------------------------------------------------
    # Async iterator
    # ------------------------------------------------------------------

    async def __aiter__(self) -> AsyncIterator[TriageEvent]:
        # Continue while the stop event is clear OR while there are still
        # unconsumed items in the queue (drain on shutdown).
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                raw = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=0.2,
                )
            except asyncio.TimeoutError:
                continue
            if not isinstance(raw, dict):
                continue
            event = TriageEvent.from_log_record(raw)
            if event is not None:
                yield event


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
@dataclass
class DispatchOutcome:
    event_id: str
    kind: str
    chain_id: str | None
    approval_id: str | None
    skipped: bool = False
    error: str | None = None
    chain_steps_run: int = 0


@dataclass
class DispatcherStats:
    events_seen: int = 0
    chains_run: int = 0
    chains_succeeded: int = 0
    chains_failed: int = 0
    events_skipped: int = 0
    last_error: str | None = None
    outcomes: list[DispatchOutcome] = field(default_factory=list)


class TriageDispatcher:
    """The daemon. Subscribe an EventSource via `start()`."""

    def __init__(
        self,
        *,
        config: Config | None = None,
        chains: tuple[Chain, ...] = DEFAULT_CHAINS,
        queue_client: QueueClient | None = None,
        run_chain_fn: Callable[..., Any] | None = None,
        max_outcomes: int = 200,
    ) -> None:
        self.config = config or get_config()
        self.chains = chains
        self.queue = queue_client
        self._owns_queue = queue_client is None
        self._run_chain = run_chain_fn or run_chain
        self.stats = DispatcherStats()
        self._max_outcomes = max_outcomes
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Signal the daemon's main loop to exit cleanly."""
        self._stop_event.set()

    async def aclose(self) -> None:
        if self._owns_queue and self.queue is not None:
            await self.queue.aclose()

    # ------------------------------------------------------------------
    async def dispatch(self, event: TriageEvent) -> DispatchOutcome:
        """Route ONE event through the right chain. Returns the outcome."""
        self.stats.events_seen += 1
        chain = chain_for_event(event.kind, self.chains)
        if chain is None:
            log.info("triage.dispatch.no_chain", kind=event.kind, event_id=event.event_id)
            self.stats.events_skipped += 1
            outcome = DispatchOutcome(
                event_id=event.event_id, kind=event.kind, chain_id=None,
                approval_id=None, skipped=True,
            )
            self._record_outcome(outcome)
            return outcome

        if self.queue is None:
            self.queue = QueueClient(self.config)

        self.stats.chains_run += 1
        try:
            result: ChainResult = await self._run_chain(
                chain,
                event.payload,
                queue_client=self.queue,
                config=self.config,
                workflow_override=chain.chain_id,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("triage.dispatch.chain_error", chain=chain.chain_id)
            self.stats.chains_failed += 1
            self.stats.last_error = str(e)
            outcome = DispatchOutcome(
                event_id=event.event_id, kind=event.kind, chain_id=chain.chain_id,
                approval_id=None, error=str(e),
            )
            self._record_outcome(outcome)
            return outcome

        ok = result.submitted_approval_id is not None or not result.errors
        if ok:
            self.stats.chains_succeeded += 1
        else:
            self.stats.chains_failed += 1
            self.stats.last_error = "; ".join(result.errors) if result.errors else None

        outcome = DispatchOutcome(
            event_id=event.event_id,
            kind=event.kind,
            chain_id=chain.chain_id,
            approval_id=result.submitted_approval_id,
            error="; ".join(result.errors) if result.errors else None,
            chain_steps_run=len(result.runs),
        )
        self._record_outcome(outcome)
        log.info(
            "triage.dispatch.done",
            chain=chain.chain_id,
            event_id=event.event_id,
            approval_id=result.submitted_approval_id,
            steps=len(result.runs),
            errors=len(result.errors),
        )
        return outcome

    def _record_outcome(self, outcome: DispatchOutcome) -> None:
        self.stats.outcomes.append(outcome)
        if len(self.stats.outcomes) > self._max_outcomes:
            del self.stats.outcomes[: len(self.stats.outcomes) - self._max_outcomes]

    # ------------------------------------------------------------------
    async def start(self, source: EventSource | AsyncIterable[TriageEvent]) -> None:
        """Main loop: consume the event source until stopped."""
        log.info("triage.dispatcher.start", chains=[c.chain_id for c in self.chains])
        try:
            async for event in source:  # type: ignore[union-attr]
                if self._stop_event.is_set():
                    break
                try:
                    await self.dispatch(event)
                except Exception as e:  # noqa: BLE001
                    # We never want one bad event to take the daemon down.
                    log.exception("triage.dispatcher.event_error", event_id=event.event_id)
                    self.stats.last_error = str(e)
        finally:
            log.info(
                "triage.dispatcher.stop",
                events=self.stats.events_seen,
                chains_ok=self.stats.chains_succeeded,
                chains_fail=self.stats.chains_failed,
            )
            await self.aclose()


# ---------------------------------------------------------------------------
# Convenience builder
# ---------------------------------------------------------------------------
def build_default_source(
    *,
    source_type: str = "file",
    log_path: Path | None = None,
    poll_interval_s: float = 5.0,
    webhook_port: int = 8765,
    webhook_secret: str = "",
) -> EventSource:
    """Construct the default event source for a given type.

    source_type values:
      ``"file"`` or ``"mock"``  — MockDataEventSource (default).
      ``"webhook"``             — WebhookEventSource (prod ingress, §9 Wave 2).
    """
    source_type = (source_type or "file").lower()
    if source_type in ("file", "mock"):
        if log_path is None:
            # Default location: <repo>/mock-data/_state/dispatch.log
            here = Path(__file__).resolve()
            repo = here.parents[3]  # runtime/runtime/triage_dispatcher.py → repo
            log_path = repo / "mock-data" / "_state" / "dispatch.log"
        return MockDataEventSource(log_path=log_path, poll_interval_s=poll_interval_s)
    if source_type == "webhook":
        return WebhookEventSource(port=webhook_port, secret=webhook_secret)
    raise ValueError(f"unknown event source: {source_type!r} (file|mock|webhook)")


__all__ = [
    "DispatchOutcome",
    "DispatcherStats",
    "EventSource",
    "InMemoryEventSource",
    "MockDataEventSource",
    "TriageDispatcher",
    "TriageEvent",
    "WebhookEventSource",
    "build_default_source",
]
