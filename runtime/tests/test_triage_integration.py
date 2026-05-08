"""Integration test: mock-data dispatcher writes dispatch.log → TriageDispatcher
picks up events → chain runs → combined queue item submitted.

We mock the chain at the run_chain seam so we don't need a live LLM, but we
exercise the *real* MockDataEventSource against a real dispatch.log written
by the *real* mock-data Dispatcher.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from runtime.chains import Chain, ChainResult, Step
from runtime.triage_dispatcher import (
    MockDataEventSource,
    TriageDispatcher,
    TriageEvent,
)


def _mock_data_available() -> bool:
    return importlib.util.find_spec("quill_mock_data") is not None


pytestmark = pytest.mark.skipif(
    not _mock_data_available(),
    reason="mock-data package not importable in this env",
)


@pytest.mark.asyncio
async def test_dispatch_log_to_triage_dispatcher_end_to_end(tmp_path: Path, monkeypatch):
    """Real Dispatcher writes a real dispatch.log; real source consumes; chain mocked."""
    # Point the mock-data dispatcher at a tmp dispatch.log so we don't pollute
    # the repo's _state dir.
    from quill_mock_data import dispatcher as md_dispatcher
    log_path = tmp_path / "dispatch.log"
    monkeypatch.setattr(md_dispatcher, "DISPATCH_LOG", log_path)

    # 1. Generate a real RFI event via the real feeder.
    from quill_mock_data.feeders import rfi as rfi_feeder
    events = rfi_feeder.tick(target_count=1, seed=42)
    assert events, "feeder produced no events"

    # 2. Run the real Dispatcher in dry_run mode (writes to dispatch.log).
    async with md_dispatcher.Dispatcher(dry_run=True) as d:
        result = await d.dispatch(events[0])
    assert result["status"] == "dry_run"
    assert log_path.exists()

    # The log line must include a `payload` field (Phase F.1 enhancement).
    line = log_path.read_text(encoding="utf-8").splitlines()[-1]
    rec = json.loads(line)
    assert rec["kind"] == "rfi.new"
    assert "payload" in rec
    assert rec["payload"]["rfi_id"].startswith("RFI-")
    assert "event_id" in rec

    # 3. Wire the real MockDataEventSource against the same file.
    src = MockDataEventSource(log_path, poll_interval_s=0.05)
    seen_events: list[TriageEvent] = []
    submitted_payloads: list[dict[str, Any]] = []

    async def fake_run_chain(chain, event_payload, **kwargs):
        submitted_payloads.append({"chain": chain.chain_id, "payload": event_payload})
        return ChainResult(
            chain_id=chain.chain_id,
            runs=[],
            skipped=[],
            errors=[],
            submitted_approval_id=f"appr-{chain.chain_id}",
        )

    rfi_chain = Chain(
        chain_id="rfi.full_triage",
        event_kinds=("rfi.new",),
        steps=(Step("rfi-triage"),),
    )
    dispatcher = TriageDispatcher(
        config=MagicMock(),
        chains=(rfi_chain,),
        queue_client=MagicMock(),
        run_chain_fn=fake_run_chain,
    )

    # Consume one event then stop.
    async def consumer():
        async for event in src:
            seen_events.append(event)
            await dispatcher.dispatch(event)
            src.stop()

    await asyncio.wait_for(consumer(), timeout=5.0)

    # 4. Verify the dispatcher picked up the RFI event with the right payload.
    assert len(seen_events) == 1
    e = seen_events[0]
    assert e.kind == "rfi.new"
    assert e.payload["rfi_id"] == rec["payload"]["rfi_id"]

    # 5. Verify a chain was run with that payload.
    assert len(submitted_payloads) == 1
    assert submitted_payloads[0]["chain"] == "rfi.full_triage"
    assert submitted_payloads[0]["payload"]["rfi_id"].startswith("RFI-")

    assert dispatcher.stats.chains_succeeded == 1
    assert dispatcher.stats.events_seen == 1


@pytest.mark.asyncio
async def test_dispatcher_picks_up_event_within_5_seconds(tmp_path: Path, monkeypatch):
    """Charles's quality bar: queue item shows up within seconds of feeder event."""
    from quill_mock_data import dispatcher as md_dispatcher
    log_path = tmp_path / "dispatch.log"
    monkeypatch.setattr(md_dispatcher, "DISPATCH_LOG", log_path)

    log_path.touch()  # exist so source can poll

    src = MockDataEventSource(log_path, poll_interval_s=0.1)
    rfi_chain = Chain(
        chain_id="rfi.full_triage",
        event_kinds=("rfi.new",),
        steps=(Step("rfi-triage"),),
    )

    async def fake_run_chain(chain, payload, **kwargs):
        return ChainResult(
            chain_id=chain.chain_id, runs=[], skipped=[], errors=[],
            submitted_approval_id="appr-fast",
        )

    dispatcher = TriageDispatcher(
        config=MagicMock(), chains=(rfi_chain,), queue_client=MagicMock(),
        run_chain_fn=fake_run_chain,
    )

    seen: list[TriageEvent] = []

    async def consumer():
        async for event in src:
            seen.append(event)
            await dispatcher.dispatch(event)
            src.stop()

    async def feeder():
        # Brief delay then produce + post an event.
        await asyncio.sleep(0.2)
        from quill_mock_data.feeders import rfi as rfi_feeder
        events = rfi_feeder.tick(target_count=1, seed=99)
        async with md_dispatcher.Dispatcher(dry_run=True) as d:
            await d.dispatch(events[0])

    start = asyncio.get_event_loop().time()
    await asyncio.wait_for(asyncio.gather(consumer(), feeder()), timeout=5.0)
    elapsed = asyncio.get_event_loop().time() - start

    assert len(seen) == 1
    assert elapsed < 5.0
    assert dispatcher.stats.chains_succeeded == 1
