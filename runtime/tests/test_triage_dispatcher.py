"""Tests for runtime.triage_dispatcher — daemon, mock event source, dispatch routing."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from runtime.chains import Chain, ChainResult, Step
from runtime.triage_dispatcher import (
    DispatchOutcome,
    InMemoryEventSource,
    MockDataEventSource,
    TriageDispatcher,
    TriageEvent,
    build_default_source,
)


# ---------------------------------------------------------------------------
# TriageEvent.from_log_record
# ---------------------------------------------------------------------------
def test_from_log_record_builds_event():
    rec = {
        "ts": "2026-05-08T12:00:00Z",
        "kind": "rfi.new",
        "source": "feeder",
        "status": "submitted",
        "approval_id": "appr-abc",
        "summary": "RFI-001 structural on B-3",
        "agent_id": "rfi-triage",
    }
    e = TriageEvent.from_log_record(rec)
    assert e is not None
    assert e.event_id == "appr-abc"
    assert e.kind == "rfi.new"
    assert e.payload["summary"] == "RFI-001 structural on B-3"


def test_from_log_record_skips_skipped_entries():
    rec = {"kind": "rfi.new", "status": "skipped"}
    assert TriageEvent.from_log_record(rec) is None


def test_from_log_record_skips_errored_entries():
    rec = {"kind": "rfi.new", "status": "http_error"}
    assert TriageEvent.from_log_record(rec) is None


def test_from_log_record_skips_no_kind():
    assert TriageEvent.from_log_record({"status": "submitted"}) is None


# ---------------------------------------------------------------------------
# MockDataEventSource — file polling, cursor, dedup
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mockdata_source_yields_new_events_and_advances_cursor(tmp_path: Path):
    log_file = tmp_path / "dispatch.log"
    log_file.write_text(
        json.dumps({"kind": "rfi.new", "status": "submitted", "approval_id": "a1", "summary": "x"})
        + "\n"
        + json.dumps({"kind": "submittal.new", "status": "submitted", "approval_id": "a2", "summary": "y"})
        + "\n",
        encoding="utf-8",
    )
    src = MockDataEventSource(log_file, poll_interval_s=0.05)
    seen: list[TriageEvent] = []

    async def consume():
        async for e in src:
            seen.append(e)
            if len(seen) >= 2:
                src.stop()

    await asyncio.wait_for(consume(), timeout=2.0)
    assert [e.event_id for e in seen] == ["a1", "a2"]
    assert src.cursor_path.exists()
    assert int(src.cursor_path.read_text()) == log_file.stat().st_size


@pytest.mark.asyncio
async def test_mockdata_source_dedupes_same_event_id(tmp_path: Path):
    log_file = tmp_path / "dispatch.log"
    rec = {"kind": "rfi.new", "status": "submitted", "approval_id": "dup-1", "summary": "x"}
    log_file.write_text(json.dumps(rec) + "\n" + json.dumps(rec) + "\n", encoding="utf-8")

    src = MockDataEventSource(log_file, poll_interval_s=0.05)
    seen = []

    async def consume():
        async for e in src:
            seen.append(e)
            # Stop quickly — both lines are in the file.
            await asyncio.sleep(0.01)
            src.stop()

    await asyncio.wait_for(consume(), timeout=2.0)
    assert len(seen) == 1
    assert seen[0].event_id == "dup-1"


@pytest.mark.asyncio
async def test_mockdata_source_picks_up_appended_lines(tmp_path: Path):
    log_file = tmp_path / "dispatch.log"
    log_file.write_text(
        json.dumps({"kind": "rfi.new", "status": "submitted", "approval_id": "a1", "summary": "x"}) + "\n",
        encoding="utf-8",
    )

    src = MockDataEventSource(log_file, poll_interval_s=0.05)
    seen = []

    async def consume():
        async for e in src:
            seen.append(e)
            if len(seen) == 2:
                src.stop()

    async def appender():
        await asyncio.sleep(0.15)
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {"kind": "submittal.new", "status": "submitted", "approval_id": "a2", "summary": "y"}
                )
                + "\n"
            )

    await asyncio.wait_for(asyncio.gather(consume(), appender()), timeout=3.0)
    assert [e.event_id for e in seen] == ["a1", "a2"]


@pytest.mark.asyncio
async def test_mockdata_source_resumes_from_cursor(tmp_path: Path):
    log_file = tmp_path / "dispatch.log"
    log_file.write_text(
        json.dumps({"kind": "rfi.new", "status": "submitted", "approval_id": "a1", "summary": "x"}) + "\n",
        encoding="utf-8",
    )
    cursor_file = log_file.with_suffix(log_file.suffix + ".cursor")
    # Pre-seed cursor at end of file → first record should be skipped.
    cursor_file.write_text(str(log_file.stat().st_size), encoding="utf-8")

    # Now append a second record post-cursor.
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {"kind": "submittal.new", "status": "submitted", "approval_id": "a2", "summary": "y"}
            )
            + "\n"
        )

    src = MockDataEventSource(log_file, poll_interval_s=0.05)
    seen = []

    async def consume():
        async for e in src:
            seen.append(e)
            src.stop()

    await asyncio.wait_for(consume(), timeout=2.0)
    assert [e.event_id for e in seen] == ["a2"]


@pytest.mark.asyncio
async def test_mockdata_source_handles_partial_trailing_line(tmp_path: Path):
    log_file = tmp_path / "dispatch.log"
    # Write one complete line + a partial (no trailing newline).
    log_file.write_text(
        json.dumps({"kind": "rfi.new", "status": "submitted", "approval_id": "a1", "summary": "x"})
        + "\n"
        + '{"kind": "submittal.new", "status": "submi',  # truncated
        encoding="utf-8",
    )
    src = MockDataEventSource(log_file, poll_interval_s=0.05)
    seen = []

    async def consume():
        async for e in src:
            seen.append(e)
            src.stop()

    await asyncio.wait_for(consume(), timeout=2.0)
    assert len(seen) == 1
    assert seen[0].event_id == "a1"


# ---------------------------------------------------------------------------
# TriageDispatcher — routing
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatcher_skips_unknown_event_kind(monkeypatch):
    dispatcher = TriageDispatcher(
        config=MagicMock(),
        chains=(),  # no chains registered
        queue_client=MagicMock(),
        run_chain_fn=AsyncMock(),
    )
    e = TriageEvent(event_id="e1", kind="nope.unknown", payload={})
    outcome = await dispatcher.dispatch(e)
    assert outcome.skipped is True
    assert outcome.chain_id is None
    assert dispatcher.stats.events_skipped == 1
    dispatcher._run_chain.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatcher_routes_rfi_to_rfi_chain():
    fake_chain = Chain(
        chain_id="rfi.full_triage",
        event_kinds=("rfi.new",),
        steps=(Step("rfi-triage"),),
    )
    fake_run_chain = AsyncMock(
        return_value=ChainResult(
            chain_id="rfi.full_triage",
            runs=[],
            skipped=[],
            errors=[],
            submitted_approval_id="appr-fake-1",
        )
    )
    dispatcher = TriageDispatcher(
        config=MagicMock(),
        chains=(fake_chain,),
        queue_client=MagicMock(),
        run_chain_fn=fake_run_chain,
    )
    e = TriageEvent(event_id="e2", kind="rfi.new", payload={"rfi_id": "RFI-1"})
    outcome = await dispatcher.dispatch(e)

    assert outcome.chain_id == "rfi.full_triage"
    assert outcome.approval_id == "appr-fake-1"
    assert outcome.error is None
    assert dispatcher.stats.chains_run == 1
    assert dispatcher.stats.chains_succeeded == 1
    fake_run_chain.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatcher_handles_chain_exception():
    fake_chain = Chain(
        chain_id="rfi.full_triage",
        event_kinds=("rfi.new",),
        steps=(Step("rfi-triage"),),
    )
    fake_run_chain = AsyncMock(side_effect=RuntimeError("boom"))
    dispatcher = TriageDispatcher(
        config=MagicMock(),
        chains=(fake_chain,),
        queue_client=MagicMock(),
        run_chain_fn=fake_run_chain,
    )
    e = TriageEvent(event_id="e3", kind="rfi.new", payload={})
    outcome = await dispatcher.dispatch(e)

    assert outcome.error is not None
    assert "boom" in outcome.error
    assert dispatcher.stats.chains_failed == 1
    assert dispatcher.stats.last_error == "boom"


@pytest.mark.asyncio
async def test_dispatcher_start_consumes_in_memory_source():
    fake_chain = Chain(
        chain_id="rfi.full_triage",
        event_kinds=("rfi.new",),
        steps=(Step("rfi-triage"),),
    )
    n_calls = 0

    async def fake_run(*args, **kwargs):
        nonlocal n_calls
        n_calls += 1
        return ChainResult(
            chain_id="rfi.full_triage", runs=[], skipped=[], errors=[],
            submitted_approval_id=f"appr-{n_calls}",
        )

    dispatcher = TriageDispatcher(
        config=MagicMock(),
        chains=(fake_chain,),
        queue_client=MagicMock(),
        run_chain_fn=fake_run,
    )
    events = [
        TriageEvent(event_id=f"e{i}", kind="rfi.new", payload={"i": i}) for i in range(3)
    ]
    src = InMemoryEventSource(events)
    await asyncio.wait_for(dispatcher.start(src), timeout=2.0)

    assert n_calls == 3
    assert dispatcher.stats.events_seen == 3
    assert dispatcher.stats.chains_succeeded == 3
    assert len(dispatcher.stats.outcomes) == 3


@pytest.mark.asyncio
async def test_dispatcher_start_continues_through_event_errors():
    fake_chain = Chain(
        chain_id="rfi.full_triage",
        event_kinds=("rfi.new",),
        steps=(Step("rfi-triage"),),
    )

    calls = 0

    async def flaky_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("transient")
        return ChainResult(chain_id="rfi.full_triage", runs=[], skipped=[], errors=[],
                           submitted_approval_id=f"a-{calls}")

    dispatcher = TriageDispatcher(
        config=MagicMock(),
        chains=(fake_chain,),
        queue_client=MagicMock(),
        run_chain_fn=flaky_run,
    )
    events = [
        TriageEvent(event_id=f"e{i}", kind="rfi.new", payload={}) for i in range(3)
    ]
    await asyncio.wait_for(
        dispatcher.start(InMemoryEventSource(events)), timeout=2.0
    )
    # We saw all 3 events even though one chain raised.
    assert dispatcher.stats.events_seen == 3
    assert dispatcher.stats.chains_succeeded == 2
    assert dispatcher.stats.chains_failed == 1


# ---------------------------------------------------------------------------
# build_default_source
# ---------------------------------------------------------------------------
def test_build_default_source_mock(tmp_path: Path):
    log = tmp_path / "dispatch.log"
    src = build_default_source(source_type="mock", log_path=log, poll_interval_s=0.1)
    assert isinstance(src, MockDataEventSource)
    assert src.poll_interval_s == 0.1


def test_build_default_source_webhook_implemented():
    """webhook source is now implemented (§9 Wave 2)."""
    from runtime.triage_dispatcher import WebhookEventSource
    src = build_default_source(source_type="webhook", webhook_port=19876)
    assert isinstance(src, WebhookEventSource)
    assert src.port == 19876


def test_build_default_source_unknown_type_raises():
    with pytest.raises(ValueError):
        build_default_source(source_type="zzz")
