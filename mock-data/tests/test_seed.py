"""Seed/bootstrap data tests."""

from __future__ import annotations

from quill_mock_data.project import QPB1, building_codes, superintendent_for
from quill_mock_data.seed import (
    SPEC_SECTIONS,
    SUBS,
    build_ims_xer,
    build_pos,
)


def test_qpb1_has_four_buildings():
    assert len(QPB1.buildings) == 4
    codes = building_codes()
    assert codes == ["BLDG1", "BLDG2", "BLDG3", "BLDG4"]


def test_each_building_has_a_super():
    for c in building_codes():
        assert superintendent_for(c) != "Unknown Super"


def test_spec_corpus_has_twelve_sections():
    assert len(SPEC_SECTIONS) == 12
    for s in SPEC_SECTIONS:
        assert s["section"]
        assert s["title"]
        assert s["summary"]


def test_sub_roster_has_25():
    assert len(SUBS) == 25
    trades = {s["trade"] for s in SUBS}
    assert "concrete" in trades
    assert "electrical_high_voltage" in trades


def test_long_lead_pos_count_30_with_unique_ids():
    pos = build_pos()
    assert len(pos) == 30
    ids = [p.po_id for p in pos]
    assert len(set(ids)) == 30
    for p in pos:
        assert p.vendor
        assert p.csi
        assert p.agreed_ship_date


def test_ims_xer_emits_minimum_500_activities():
    xer = build_ims_xer(activities_per_building=125)
    # 4 * 125 = 500 activity rows; XER includes %T/%F/%R header rows too.
    activity_rows = [line for line in xer.splitlines() if line.startswith("%R\t1") and "BLDG" in line]
    # build_ims_xer rows are tab-delimited and the activity rows include task_name with BLDG prefix.
    assert len(activity_rows) >= 500


def test_hyperscaler_reps_count():
    assert len(QPB1.hyperscaler_reps) == 5
