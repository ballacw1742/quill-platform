"""Dispatcher routing tests — dry-run mode (no HTTP)."""

from __future__ import annotations

from datetime import date

import pytest

from quill_mock_data.dispatcher import Dispatcher, dispatch_many
from quill_mock_data.feeders import dfr as dfr_feeder
from quill_mock_data.feeders import hyperscaler as hyperscaler_feeder
from quill_mock_data.feeders import procurement as procurement_feeder
from quill_mock_data.feeders import rfi as rfi_feeder
from quill_mock_data.feeders import submittal as submittal_feeder


def test_rfi_event_builds_lane2_rfi_triage_payload():
    events = rfi_feeder.tick(target_count=1, seed=11)
    d = Dispatcher(dry_run=True)
    body = d.build_payload(events[0])
    assert body is not None
    assert body["agent_id"] == "rfi-triage"
    assert body["lane"] == 2
    assert body["workflow"] == "rfi.classify"
    assert body["payload"]["rfi_id"].startswith("RFI-")
    assert any(c["source_type"] == "spec_section" for c in body["citations"])


def test_submittal_non_conforming_routes_to_validator_lane2():
    # Force non-conforming by retrying until one shows up
    body = None
    for seed in range(100):
        events = submittal_feeder.tick(target_count=1, seed=seed)
        if events[0].payload["contents"]["compliant"] is False:
            body = Dispatcher(dry_run=True).build_payload(events[0])
            break
    assert body is not None, "expected at least one non-conforming sample"
    assert body["agent_id"] == "submittal-spec-validator"
    assert body["lane"] == 2
    assert body["payload"]["finding"] == "non_compliant"


def test_dfr_routes_to_lane1_with_progress_proposals():
    events = dfr_feeder.tick(report_date=date(2026, 8, 1), seed=12)
    d = Dispatcher(dry_run=True)
    body = d.build_payload(events[0])
    assert body["agent_id"] == "daily-brief"
    assert body["lane"] == 1
    assert body["target_system"] == "p6"
    assert "progress_proposals" in body["payload"]


def test_procurement_no_slip_status_only_is_skipped_or_lane1():
    # Find one with slip=0 and a non-shipping kind to confirm skip behavior
    skipped = False
    for seed in range(100):
        events = procurement_feeder.tick(target_count=1, seed=seed)
        if (events[0].payload["slip_weeks"] == 0
                and events[0].payload["kind"] not in {"shipped", "delivery_confirmed", "delay_notice"}):
            body = Dispatcher(dry_run=True).build_payload(events[0])
            if body is None:
                skipped = True
                break
    assert skipped, "expected at least one no-op procurement event"


def test_procurement_critical_slip_routes_lane3():
    # Force a high-slip case via the make_update fallback path
    from quill_mock_data.feeders.procurement import _make_update
    import random
    rng = random.Random(0)
    # Manufacture a delay_notice with a 4-week slip to land Lane 3
    fake_po = {
        "po_id": "PO-2026-1001", "item": "thing", "vendor": "ACME",
        "csi": "26 13 13", "quantity": 1,
        "agreed_ship_date": "2027-01-01", "cp_activity_refs": ["A1234"],
    }
    event_payload = _make_update(rng, fake_po)
    event_payload["kind"] = "delay_notice"
    event_payload["slip_weeks"] = 4
    event_payload["revised_ship_date"] = "2027-02-01"
    body = Dispatcher(dry_run=True).build_payload(_FakeEvent("procurement.update", event_payload))
    assert body is not None
    assert body["lane"] == 3
    assert body["priority"] == "critical_path"


def test_hyperscaler_owner_directive_lane3():
    # Loop until we hit owner_directive or milestone_update
    body = None
    for seed in range(100):
        events = hyperscaler_feeder.tick(target_count=1, seed=seed)
        if events[0].payload["kind"] in {"owner_directive", "milestone_update"}:
            body = Dispatcher(dry_run=True).build_payload(events[0])
            break
    assert body is not None
    assert body["lane"] == 3


@pytest.mark.asyncio
async def test_dispatch_many_dry_run_succeeds():
    events = rfi_feeder.tick(target_count=3, seed=13)
    out = await dispatch_many(events, dry_run=True)
    assert len(out) == 3
    assert all(o["status"] == "dry_run" for o in out)


# Tiny event impostor for the procurement-critical test
from dataclasses import dataclass


@dataclass
class _FakeEvent:
    kind: str
    payload: dict
    source: str = "test"
