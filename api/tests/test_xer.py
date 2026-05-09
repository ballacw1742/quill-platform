"""Phase G.4 — Primavera P6 XER exporter tests.

We don't try to round-trip into a live P6 instance. Instead we verify
that the XER text:
  1. starts with a valid ERMHDR record
  2. contains the expected tables (PROJECT, CALENDAR, PROJWBS, TASK, TASKPRED)
  3. uses tab separators consistently (each %R has the same column count
     as the preceding %F)
  4. ends with %E (end-of-file marker)
  5. round-trips activity ids and relationship types from the input
"""

from __future__ import annotations

import pytest

from app.services.xer import (
    ERMHDR_VERSION,
    PRED_TYPES,
    ScheduleToXer,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mini_package() -> dict:
    """A minimal valid cost_schedule_package with 4 activities + 3
    predecessors covering FS / SS / FF lag types."""
    return {
        "artifact_type": "cost_schedule_package",
        "title": "Class 5 Estimate — Test Project",
        "project_label": "QPB1-test",
        "metadata": {
            "aace_class": "5",
            "schedule_level": 1,
            "schedule": {
                "level": 1,
                "activities": [
                    {
                        "id": "A100",
                        "name": "Site mobilization",
                        "wbs": "1.1",
                        "duration_days": 10,
                        "predecessors": [],
                        "milestone": False,
                    },
                    {
                        "id": "A200",
                        "name": "Sitework — earthwork",
                        "wbs": "1.2",
                        "duration_days": 30,
                        "predecessors": [{"id": "A100", "type": "FS", "lag_days": 0}],
                        "milestone": False,
                    },
                    {
                        "id": "A300",
                        "name": "Foundations",
                        "wbs": "1.3.1",
                        "duration_days": 45,
                        "predecessors": [{"id": "A200", "type": "FS", "lag_days": 5}],
                    },
                    {
                        "id": "M100",
                        "name": "Power-on",
                        "wbs": "1.4",
                        "duration_days": 0,
                        "predecessors": [
                            {"id": "A300", "type": "FF", "lag_days": 0},
                            {"id": "A200", "type": "SS", "lag_days": 10},
                        ],
                        "milestone": True,
                    },
                ],
                "milestones": [],
                "total_duration_days": 85,
                "critical_path_ids": ["A100", "A200", "A300"],
            },
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_xer_starts_with_ermhdr(mini_package):
    out = ScheduleToXer().generate_xer(mini_package)
    assert out.startswith(f"ERMHDR\t{ERMHDR_VERSION}\t")
    assert "USD" in out.split("\n")[0]


def test_xer_contains_required_tables(mini_package):
    out = ScheduleToXer().generate_xer(mini_package)
    for tbl in ("PROJECT", "CALENDAR", "PROJWBS", "TASK", "TASKPRED"):
        assert f"%T\t{tbl}" in out, f"missing table {tbl}"


def test_xer_ends_with_eof_marker(mini_package):
    out = ScheduleToXer().generate_xer(mini_package)
    assert out.rstrip().endswith("%E")


def test_xer_records_have_consistent_column_counts(mini_package):
    """For each %T block, every %R row must have exactly the same number of
    tab-separated cells as the preceding %F header."""
    out = ScheduleToXer().generate_xer(mini_package)
    current_field_count: int | None = None
    current_table: str | None = None
    for raw_line in out.splitlines():
        line = raw_line.rstrip("\n")
        if line.startswith("ERMHDR") or line.startswith("%E") or not line:
            continue
        cells = line.split("\t")
        marker = cells[0]
        if marker == "%T":
            current_table = cells[1] if len(cells) > 1 else None
            current_field_count = None
        elif marker == "%F":
            # %F + N field names → record rows have N+1 cells (the %R prefix
            # plus N value cells)
            current_field_count = len(cells) - 1
        elif marker == "%R":
            assert current_field_count is not None, (
                f"saw %R without preceding %F (table={current_table})"
            )
            actual = len(cells) - 1
            assert actual == current_field_count, (
                f"table {current_table}: %R has {actual} cells, "
                f"expected {current_field_count} (line={line[:120]})"
            )


def test_xer_emits_one_task_per_activity(mini_package):
    out = ScheduleToXer().generate_xer(mini_package)
    # Find the TASK table
    in_task = False
    task_rows = 0
    for line in out.splitlines():
        if line.startswith("%T\t"):
            in_task = line == "%T\tTASK"
            continue
        if in_task and line.startswith("%R\t"):
            task_rows += 1
    assert task_rows == 4  # 4 activities in mini_package


def test_xer_emits_one_taskpred_per_relationship(mini_package):
    out = ScheduleToXer().generate_xer(mini_package)
    in_pred = False
    pred_rows = 0
    for line in out.splitlines():
        if line.startswith("%T\t"):
            in_pred = line == "%T\tTASKPRED"
            continue
        if in_pred and line.startswith("%R\t"):
            pred_rows += 1
    # mini_package has 1 (A200<-A100) + 1 (A300<-A200) + 2 (M100<-A300, M100<-A200) = 4
    assert pred_rows == 4


def test_xer_relationship_types_translated_to_p6_codes(mini_package):
    out = ScheduleToXer().generate_xer(mini_package)
    # FS → PR_FS, SS → PR_SS, FF → PR_FF
    assert PRED_TYPES["FS"] in out
    assert PRED_TYPES["SS"] in out
    assert PRED_TYPES["FF"] in out


def test_xer_milestone_uses_milestone_task_type(mini_package):
    out = ScheduleToXer().generate_xer(mini_package)
    # M100 is the only milestone; TT_Mile must appear for it.
    assert "TT_Mile" in out


def test_xer_wbs_paths_emit_one_row_per_unique_path(mini_package):
    out = ScheduleToXer().generate_xer(mini_package)
    in_wbs = False
    wbs_rows = 0
    for line in out.splitlines():
        if line.startswith("%T\t"):
            in_wbs = line == "%T\tPROJWBS"
            continue
        if in_wbs and line.startswith("%R\t"):
            wbs_rows += 1
    # ROOT + paths: 1, 1.1, 1.2, 1.3, 1.3.1, 1.4 = 1 + 6 = 7
    assert wbs_rows == 7


def test_xer_raises_when_no_activities():
    pkg = {"metadata": {"schedule": {"activities": []}}}
    with pytest.raises(ValueError, match="no schedule.activities"):
        ScheduleToXer().generate_xer(pkg)


def test_xer_handles_metadata_passed_directly():
    """Caller may pass either a full artifact or just the metadata block."""
    metadata = {
        "schedule": {
            "activities": [
                {"id": "A1", "name": "Only", "wbs": "1", "duration_days": 1,
                 "predecessors": []}
            ]
        }
    }
    out = ScheduleToXer().generate_xer(metadata)
    assert "%T\tTASK" in out
    assert "Only" in out


def test_xer_safe_ids_for_unsafe_input():
    pkg = {
        "metadata": {
            "schedule": {
                "activities": [
                    {"id": "A/with/slashes", "name": "weird", "wbs": "1",
                     "duration_days": 1, "predecessors": []},
                ]
            }
        }
    }
    out = ScheduleToXer().generate_xer(pkg)
    # Slashes get stripped by _safe_task_id; the cleaned id should appear.
    assert "Awithslashes" in out
    # Original unsafe form must NOT appear in the output (would corrupt P6)
    assert "A/with/slashes" not in out


def test_xer_duration_converts_days_to_hours(mini_package):
    out = ScheduleToXer().generate_xer(mini_package)
    # A300 has 45 days → 360.00 hours
    assert "360.00" in out
    # A100 has 10 days → 80.00 hours
    assert "80.00" in out


def test_xer_calendar_block_present(mini_package):
    out = ScheduleToXer().generate_xer(mini_package)
    # Default calendar should mention 8.0 day hours / 40.0 week hours
    assert "8.0" in out
    assert "40.0" in out
    assert "Standard" in out
