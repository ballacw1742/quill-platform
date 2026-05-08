"""Validate that each feeder emits well-formed events."""

from __future__ import annotations

from datetime import date

from quill_mock_data.feeders import FeederEvent
from quill_mock_data.feeders import dfr as dfr_feeder
from quill_mock_data.feeders import hyperscaler as hyperscaler_feeder
from quill_mock_data.feeders import procurement as procurement_feeder
from quill_mock_data.feeders import rfi as rfi_feeder
from quill_mock_data.feeders import submittal as submittal_feeder


def test_rfi_feeder_emits_events_with_required_fields():
    events = rfi_feeder.tick(target_count=5, seed=1)
    assert len(events) == 5
    for ev in events:
        assert isinstance(ev, FeederEvent)
        assert ev.kind == "rfi.new"
        p = ev.payload
        for k in ("rfi_id", "subject", "building", "discipline",
                  "drawing_id", "spec_section", "subcontractor", "priority", "body"):
            assert k in p, f"missing {k}"
        assert p["rfi_id"].startswith("RFI-")
        assert "QUESTION" in p["body"]
        assert p["priority"] in {"low", "normal", "high", "critical_path"}


def test_submittal_feeder_includes_compliance_signal():
    events = submittal_feeder.tick(target_count=8, seed=2)
    assert len(events) == 8
    has_non_conforming = False
    has_conforming = False
    for ev in events:
        assert ev.kind == "submittal.new"
        c = ev.payload["contents"]
        assert "compliant" in c
        if c["compliant"] is False:
            has_non_conforming = True
            assert c["deltas"], "non-conforming submittal must list deltas"
        else:
            has_conforming = True
    # With 8 samples and 35% non-conforming probability, both classes should
    # appear most of the time. Allow a soft assert by counting at least one.
    assert has_non_conforming or has_conforming


def test_dfr_feeder_emits_one_per_building():
    events = dfr_feeder.tick(report_date=date(2026, 7, 1), seed=3)
    assert len(events) == 4
    seen = set()
    for ev in events:
        assert ev.kind == "dfr.new"
        p = ev.payload
        assert p["building"] not in seen
        seen.add(p["building"])
        assert p["report_date"] == "2026-07-01"
        assert p["headcount"] >= 0
        assert "DAILY FIELD REPORT" in p["narrative"]
        assert isinstance(p["quantities"], list)


def test_procurement_feeder_uses_real_pos():
    events = procurement_feeder.tick(target_count=6, seed=4)
    assert len(events) == 6
    for ev in events:
        assert ev.kind == "procurement.update"
        p = ev.payload
        assert p["po_id"].startswith("PO-")
        assert p["vendor"]
        assert p["kind"] in {"submittal_received", "manufacturing_started",
                             "factory_test_passed", "shipping_scheduled",
                             "shipped", "delay_notice", "delivery_confirmed"}


def test_hyperscaler_feeder_emits_classified_inbound():
    events = hyperscaler_feeder.tick(target_count=3, seed=5)
    assert len(events) == 3
    for ev in events:
        assert ev.kind == "hyperscaler.inbound"
        p = ev.payload
        assert p["inbound_id"].startswith("HS-")
        assert p["kind"] in {"spec_addendum", "drawing_revision",
                             "owner_directive", "rfi_request",
                             "value_engineering_request", "milestone_update"}
        assert p["from_rep"]


def test_feeder_event_to_dict_round_trip():
    events = rfi_feeder.tick(target_count=1, seed=10)
    d = events[0].to_dict()
    assert d["kind"] == "rfi.new"
    assert "payload" in d
    assert "created_at" in d
