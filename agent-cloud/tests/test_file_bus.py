"""FileBus — local durable JSONL event bus (EVENT_BUS=file).

Tests verify:
- publish() appends a JSONL line and dispatches inline to subscribers
- replay() reads from cursor to EOF and dispatches; does not re-dispatch
  already-processed events
- cursor file survives restarts without re-processing
- malformed JSONL lines during replay are skipped with a warning
- get_bus() returns a FileBus when EVENT_BUS=file
- subscribe/publish behaviour mirrors InlineBus for in-process consumers
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from app import events as events_mod
from app.config import get_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(tenant_id: str = "test-filebus", etype: str = "turn.completed") -> dict:
    return events_mod.make_event(
        tenant_id=tenant_id,
        type=etype,
        payload={"msg": "hello"},
        agent_id="test-agent",
    )


@pytest.fixture()
def bus(tmp_path, monkeypatch):
    """A FileBus instance pointed at a temp directory."""
    events_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("EVENT_BUS", "file")
    monkeypatch.setenv("EVENT_BUS_FILE", str(events_path))
    get_settings.cache_clear()
    events_mod.reset_bus()
    b = events_mod.FileBus(path=str(events_path))
    yield b
    events_mod.reset_bus()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# publish() — JSONL write + inline dispatch
# ---------------------------------------------------------------------------


async def test_publish_appends_jsonl(bus, tmp_path):
    ev = _make_event()
    await bus.publish(ev)

    events_path = tmp_path / "events.jsonl"
    lines = events_path.read_text().strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event_id"] == ev["event_id"]
    assert parsed["type"] == "turn.completed"


async def test_publish_multiple_appends_all(bus, tmp_path):
    events_path = tmp_path / "events.jsonl"
    for _ in range(3):
        await bus.publish(_make_event())
    lines = events_path.read_text().strip().splitlines()
    assert len(lines) == 3


async def test_publish_dispatches_inline(bus):
    received = []
    bus.subscribe(lambda ev: received.append(ev["event_id"]))
    ev = _make_event()
    await bus.publish(ev)
    assert received == [ev["event_id"]]


async def test_publish_dispatch_async_subscriber(bus):
    received = []

    async def _async_sub(ev):
        received.append(ev["type"])

    bus.subscribe(_async_sub)
    await bus.publish(_make_event())
    assert received == ["turn.completed"]


async def test_published_list_populated(bus):
    ev = _make_event()
    await bus.publish(ev)
    assert len(bus.published) == 1
    assert bus.published[0]["event_id"] == ev["event_id"]


# ---------------------------------------------------------------------------
# replay() — cursor-based startup replay
# ---------------------------------------------------------------------------


async def test_replay_empty_file_is_noop(bus):
    """replay() on a non-existent file must not raise."""
    # events.jsonl hasn't been created yet
    await bus.replay()  # should silently return


async def test_replay_dispatches_unprocessed_events(bus, tmp_path):
    events_path = tmp_path / "events.jsonl"
    # Pre-populate the file directly (simulating a previous run)
    ev1 = _make_event()
    ev2 = _make_event()
    events_path.write_text(
        json.dumps(ev1) + "\n" + json.dumps(ev2) + "\n"
    )

    received = []
    bus.subscribe(lambda ev: received.append(ev["event_id"]))
    await bus.replay()
    assert ev1["event_id"] in received
    assert ev2["event_id"] in received


async def test_replay_skips_already_processed_events(bus, tmp_path):
    """Events before the cursor offset must not be re-dispatched."""
    events_path = tmp_path / "events.jsonl"
    ev1 = _make_event()
    line1 = json.dumps(ev1) + "\n"
    events_path.write_text(line1)

    # Simulate a previous successful replay by writing cursor = len(line1)
    cursor_path = events_path.with_suffix(".cursor")
    cursor_path.write_text(str(len(line1.encode("utf-8"))))

    # Add a new unprocessed event after the cursor
    ev2 = _make_event()
    with events_path.open("a") as fh:
        fh.write(json.dumps(ev2) + "\n")

    received = []
    bus.subscribe(lambda ev: received.append(ev["event_id"]))
    await bus.replay()

    # Only ev2 should be dispatched
    assert ev1["event_id"] not in received
    assert ev2["event_id"] in received


async def test_replay_advances_cursor(bus, tmp_path):
    """After replay, the cursor must point to EOF so a second replay is a noop."""
    events_path = tmp_path / "events.jsonl"
    cursor_path = events_path.with_suffix(".cursor")

    ev = _make_event()
    events_path.write_text(json.dumps(ev) + "\n")

    await bus.replay()

    # Cursor should equal file size
    file_size = events_path.stat().st_size
    cursor = int(cursor_path.read_text().strip())
    assert cursor == file_size

    # Second replay should dispatch nothing
    received = []
    bus2 = events_mod.FileBus(path=str(events_path))
    bus2.subscribe(lambda ev: received.append(ev["event_id"]))
    await bus2.replay()
    assert received == []


async def test_replay_skips_malformed_lines(bus, tmp_path, caplog):
    """Malformed JSONL lines during replay must be skipped, not raise."""
    events_path = tmp_path / "events.jsonl"
    ev = _make_event()
    events_path.write_text("NOT VALID JSON\n" + json.dumps(ev) + "\n")

    received = []
    bus.subscribe(lambda ev: received.append(ev["event_id"]))
    import logging
    with caplog.at_level(logging.WARNING, logger="agentcloud.events"):
        await bus.replay()

    # Valid event still dispatched
    assert ev["event_id"] in received


# ---------------------------------------------------------------------------
# Cursor persistence across FileBus instances (simulates restarts)
# ---------------------------------------------------------------------------


async def test_cursor_survives_restart(tmp_path, monkeypatch):
    """Two successive FileBus instances sharing a path must not re-process."""
    events_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("EVENT_BUS_FILE", str(events_path))
    get_settings.cache_clear()

    ev1 = _make_event()
    ev2 = _make_event()

    # First "run": publish ev1 and ev2; replay (processes both); advance cursor
    bus1 = events_mod.FileBus(path=str(events_path))
    await bus1.publish(ev1)
    await bus1.publish(ev2)
    # The published events are ALSO in the file, so replay will re-dispatch
    # them only if the cursor hasn't been advanced.
    # In this test, cursor is 0 initially so replay will re-read both.
    received1: list[str] = []
    bus1.subscribe(lambda ev: received1.append(ev["event_id"]))
    await bus1.replay()
    # Both events re-dispatched by replay (cursor was 0)
    assert ev1["event_id"] in received1
    assert ev2["event_id"] in received1

    # Second "run": new FileBus instance; no new events; replay should be noop
    bus2 = events_mod.FileBus(path=str(events_path))
    received2: list[str] = []
    bus2.subscribe(lambda ev: received2.append(ev["event_id"]))
    await bus2.replay()
    # Cursor was advanced to EOF by bus1.replay; nothing to re-dispatch
    assert received2 == []


# ---------------------------------------------------------------------------
# get_bus() returns FileBus when EVENT_BUS=file
# ---------------------------------------------------------------------------


def test_get_bus_returns_file_bus(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("EVENT_BUS", "file")
    monkeypatch.setenv("EVENT_BUS_FILE", str(events_path))
    get_settings.cache_clear()
    events_mod.reset_bus()
    b = events_mod.get_bus()
    assert isinstance(b, events_mod.FileBus)
    assert b.name == "file"
    events_mod.reset_bus()
    get_settings.cache_clear()


def test_get_bus_unknown_raises(monkeypatch):
    monkeypatch.setenv("EVENT_BUS", "unknown-backend")
    get_settings.cache_clear()
    events_mod.reset_bus()
    with pytest.raises(ValueError, match="unknown EVENT_BUS"):
        events_mod.get_bus()
    events_mod.reset_bus()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Parent directory creation
# ---------------------------------------------------------------------------


async def test_publish_creates_parent_dirs(tmp_path):
    nested_path = tmp_path / "deep" / "nested" / "events.jsonl"
    bus = events_mod.FileBus(path=str(nested_path))
    ev = _make_event()
    await bus.publish(ev)
    assert nested_path.exists()
    lines = nested_path.read_text().strip().splitlines()
    assert len(lines) == 1
