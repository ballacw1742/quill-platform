"""Primavera P6 XER export — Phase G.4.

Converts a `cost_schedule_package` artifact's `metadata.schedule` block
into a P6-importable XER plain-text stream.

XER format reference:
  https://docs.oracle.com/cd/E80480_01/help/HelpMain.htm
  (also widely documented in the Primavera community; format is plain
  text with tab-separated records and section markers.)

The XER format consists of:
  - ERMHDR record (version + currency + locale)
  - %T <TABLE>      \\t-separated table marker
  - %F field1 \\t field2 \\t ...     field-name header row
  - %R val1 \\t val2 \\t ...         one or more record rows
  - %E (end-of-file marker)

Tables we emit (minimum viable for P6 import + round-trip):
  - PROJECT       project header (one row)
  - CALENDAR      one default 5d8h calendar
  - PROJWBS       WBS hierarchy (one root + one node per WBS path)
  - TASK          one row per activity
  - TASKPRED      one row per relationship (predecessor link)

We deliberately skip RSRC/TASKACTV/TASKRSRC/UDFTYPE etc. for v0.1.
P6 will still import what we emit; missing optional tables are
synthesized at import time.

Quality bar: the output must be well-formed (correct section markers,
tab separators, each %R has the same column count as the preceding %F).
We don't try to round-trip into a real P6 instance — out of scope.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("quill.xer")


# ---------------------------------------------------------------------------
# XER constants
# ---------------------------------------------------------------------------
ERMHDR_VERSION = "8.5"  # Wide P6 compatibility (15.1+ accepts 8.5).
ERMHDR_LOCALE = "USD"
ERMHDR_DATE_FMT = "%Y-%m-%d %H:%M"
DEFAULT_CALENDAR_ID = "1"
DEFAULT_CALENDAR_NAME = "Standard 5-day 8-hour Workweek"

# P6 task type values
TASK_TYPE_TASK_DEPENDENT = "TT_Task"   # task-dependent (default)
TASK_TYPE_RSRC_DEPENDENT = "TT_Rsrc"
TASK_TYPE_LOE = "TT_LOE"
TASK_TYPE_MILESTONE = "TT_Mile"

# Relationship types (XER spelling)
PRED_TYPES = {"FS": "PR_FS", "SS": "PR_SS", "FF": "PR_FF", "SF": "PR_SF"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _xer_escape(s: Any) -> str:
    """Replace tab + newline so they don't break the XER record format."""
    if s is None:
        return ""
    if isinstance(s, bool):
        return "Y" if s else "N"
    s = str(s)
    return s.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _now_xer() -> str:
    return datetime.now(UTC).strftime(ERMHDR_DATE_FMT)


def _emit_table(name: str, fields: list[str], rows: list[list[Any]]) -> str:
    """Emit a single XER table block."""
    out_lines: list[str] = []
    out_lines.append(f"%T\t{name}")
    out_lines.append("%F\t" + "\t".join(fields))
    for row in rows:
        # pad/truncate row to match field count for robustness
        if len(row) < len(fields):
            row = row + [""] * (len(fields) - len(row))
        elif len(row) > len(fields):
            row = row[: len(fields)]
        out_lines.append("%R\t" + "\t".join(_xer_escape(c) for c in row))
    return "\n".join(out_lines) + "\n"


# ---------------------------------------------------------------------------
# WBS path normalisation
# ---------------------------------------------------------------------------
def _wbs_paths(activities: list[dict[str, Any]]) -> list[str]:
    """Return the unique WBS paths referenced by activities, plus all
    their parent prefixes, sorted by depth then path."""
    paths: set[str] = set()
    for a in activities:
        wbs = (a.get("wbs") or "").strip()
        if not wbs:
            continue
        parts = [p for p in wbs.split(".") if p]
        for i in range(1, len(parts) + 1):
            paths.add(".".join(parts[:i]))
    return sorted(paths, key=lambda p: (p.count("."), p))


# ---------------------------------------------------------------------------
# ScheduleToXer — main exporter
# ---------------------------------------------------------------------------
@dataclass
class ScheduleToXer:
    """Stateless transformer. Constructable with no args; supply package
    via generate_xer().
    """

    project_id: str = "QPB1"
    project_name: str = "Quill Drawing-Driven Estimate"
    base_year: str = "2026"

    def generate_xer(self, package: dict[str, Any]) -> str:
        """Produce a complete XER text stream from a cost_schedule_package
        artifact.

        `package` must be the full artifact dict (with `metadata.schedule`
        present). For convenience the function also accepts the inner
        metadata block directly.
        """
        meta = self._unwrap_metadata(package)
        schedule = meta.get("schedule") or {}
        activities = list(schedule.get("activities") or [])
        if not activities:
            raise ValueError(
                "cost_schedule_package has no schedule.activities; "
                "cannot generate XER"
            )

        title = self._title_from_package(package, meta)
        project_id = self._project_id_from_package(package, meta) or self.project_id

        out: list[str] = []
        out.append(self._ermhdr())
        out.append(self._project_table(project_id, title))
        out.append(self._calendar_table())
        out.append(self._wbs_table(project_id, activities))
        out.append(self._task_table(project_id, activities))
        out.append(self._taskpred_table(activities, project_id))
        out.append("%E\n")
        return "".join(out)

    # ------------------------------------------------------------------
    # Section emitters
    # ------------------------------------------------------------------
    def _ermhdr(self) -> str:
        # ERMHDR fields: version date currency_code 0 0 0 user_name database
        # widely-compatible header
        return (
            "ERMHDR\t" + ERMHDR_VERSION + "\t" + _now_xer() + "\t"
            + "Project\tquill\tquill\tQuill\tProject Management\t" + ERMHDR_LOCALE + "\n"
        )

    def _project_table(self, project_id: str, project_name: str) -> str:
        fields = [
            "proj_id", "proj_short_name", "proj_url",
            "plan_start_date", "plan_end_date",
            "wbs_max_sum_level", "fcst_start_date",
            "def_duration_type", "task_code_base", "task_code_step",
            "priority_num",
        ]
        today = _now_xer()
        rows = [[
            project_id,                                   # proj_id
            (project_name or "Quill")[:32],               # proj_short_name (P6: <=32 chars)
            "",                                            # proj_url
            today,                                         # plan_start_date
            today,                                         # plan_end_date
            "5",                                           # wbs_max_sum_level
            today,                                         # fcst_start_date
            "DT_FixedDUR",                                 # def_duration_type
            "1000", "10",                                  # task_code_base, task_code_step
            "10",                                          # priority_num
        ]]
        return _emit_table("PROJECT", fields, rows)

    def _calendar_table(self) -> str:
        fields = [
            "clndr_id", "clndr_name", "default_flag", "clndr_type",
            "day_hr_cnt", "week_hr_cnt", "month_hr_cnt", "year_hr_cnt",
        ]
        rows = [[
            DEFAULT_CALENDAR_ID,
            DEFAULT_CALENDAR_NAME,
            "Y", "CA_Base",
            "8.0", "40.0", "172.0", "2000.0",
        ]]
        return _emit_table("CALENDAR", fields, rows)

    def _wbs_table(self, project_id: str, activities: list[dict[str, Any]]) -> str:
        fields = ["wbs_id", "proj_id", "obs_id", "wbs_short_name", "wbs_name", "parent_wbs_id"]
        rows: list[list[Any]] = []
        # Always include a project root WBS row (P6 expects at least one).
        root_id = f"{project_id}.ROOT"
        rows.append([root_id, project_id, "", project_id, project_id, ""])

        path_to_id: dict[str, str] = {}
        for path in _wbs_paths(activities):
            wbs_id = f"{project_id}.W{len(path_to_id)+1}"
            path_to_id[path] = wbs_id
            parts = path.split(".")
            parent_path = ".".join(parts[:-1]) if len(parts) > 1 else ""
            parent_id = path_to_id.get(parent_path, root_id)
            short = parts[-1]
            rows.append([wbs_id, project_id, "", short, path, parent_id])

        # Persist for use by _task_table
        self._wbs_lookup = path_to_id
        self._root_wbs_id = root_id
        return _emit_table("PROJWBS", fields, rows)

    def _task_table(self, project_id: str, activities: list[dict[str, Any]]) -> str:
        fields = [
            "task_id", "proj_id", "wbs_id", "clndr_id", "phys_complete_pct",
            "rev_fdbk_flag", "task_code", "task_name", "duration_type",
            "task_type", "complete_pct_type", "status_code",
            "target_drtn_hr_cnt", "target_qty", "target_cost",
            "remain_drtn_hr_cnt",
            "complete_pct", "priority_type",
        ]
        rows: list[list[Any]] = []
        seen_ids: set[str] = set()
        for i, a in enumerate(activities, 1):
            tid = self._safe_task_id(a.get("id"), i, seen_ids)
            seen_ids.add(tid)
            wbs_path = (a.get("wbs") or "").strip()
            wbs_id = self._wbs_lookup.get(wbs_path, self._root_wbs_id)
            duration_days = float(a.get("duration_days") or 0)
            duration_hr = duration_days * 8.0  # 8-hour work day
            is_milestone = bool(a.get("milestone"))
            ttype = TASK_TYPE_MILESTONE if is_milestone else TASK_TYPE_TASK_DEPENDENT
            rows.append([
                tid,
                project_id,
                wbs_id,
                DEFAULT_CALENDAR_ID,
                "0",            # phys_complete_pct
                "N",            # rev_fdbk_flag
                tid,            # task_code
                (a.get("name") or tid)[:120],
                "DT_FixedDUR",  # duration_type
                ttype,
                "CP_Drtn",      # complete_pct_type
                "TK_NotStart",
                f"{duration_hr:.2f}",
                "0",            # target_qty
                "0",            # target_cost
                f"{duration_hr:.2f}",  # remain_drtn_hr_cnt
                "0",            # complete_pct
                "PT_Normal",
            ])
            # Persist mapping so TASKPRED can reference it
            self._task_id_lookup = getattr(self, "_task_id_lookup", {})
            self._task_id_lookup[a.get("id") or ""] = tid
            self._task_id_lookup[tid] = tid  # also map by xer id
        return _emit_table("TASK", fields, rows)

    def _taskpred_table(self, activities: list[dict[str, Any]], project_id: str) -> str:
        fields = [
            "task_pred_id", "task_id", "pred_task_id", "proj_id", "pred_proj_id",
            "pred_type", "lag_hr_cnt",
        ]
        rows: list[list[Any]] = []
        link_id = 0
        for a in activities:
            xer_succ = self._task_id_lookup.get(a.get("id") or "")
            if not xer_succ:
                continue
            for pred in (a.get("predecessors") or []):
                if not isinstance(pred, dict):
                    continue
                pid = pred.get("id")
                xer_pred = self._task_id_lookup.get(pid) if pid else None
                if not xer_pred:
                    continue
                ptype = PRED_TYPES.get(
                    (pred.get("type") or "FS").upper(),
                    PRED_TYPES["FS"],
                )
                lag_days = float(pred.get("lag_days") or 0)
                lag_hr = lag_days * 8.0
                link_id += 1
                rows.append([
                    str(link_id),
                    xer_succ,
                    xer_pred,
                    project_id,
                    project_id,
                    ptype,
                    f"{lag_hr:.2f}",
                ])
        return _emit_table("TASKPRED", fields, rows)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _unwrap_metadata(package: dict[str, Any]) -> dict[str, Any]:
        # Accept either a full artifact dict or just metadata.
        if "metadata" in package and isinstance(package["metadata"], dict):
            return package["metadata"]
        if "schedule" in package:
            return package
        return package.get("artifact", {}).get("metadata", package)

    @staticmethod
    def _title_from_package(package: dict[str, Any], meta: dict[str, Any]) -> str:
        return (
            package.get("title")
            or package.get("artifact", {}).get("title")
            or "Quill Drawing-Driven Estimate"
        )

    @staticmethod
    def _project_id_from_package(package: dict[str, Any], meta: dict[str, Any]) -> str | None:
        # We accept a few shapes; fall back to default if none present.
        for key in ("project_id", "proj_id", "project_label"):
            v = package.get(key) or meta.get(key)
            if v:
                # P6 proj_id is short-ish; alphanum + dash + underscore safe.
                clean = "".join(c for c in str(v) if c.isalnum() or c in "-_")[:20]
                return clean or None
        return None

    @staticmethod
    def _safe_task_id(raw: Any, index: int, seen: set[str]) -> str:
        """P6 task_code/task_id is alphanum + limited punctuation, max 40 chars."""
        if not raw:
            return f"A{index:05d}"
        cleaned = "".join(c for c in str(raw) if c.isalnum() or c in "-_.")[:40]
        if not cleaned:
            cleaned = f"A{index:05d}"
        # Disambiguate duplicates
        base = cleaned
        n = 1
        while cleaned in seen:
            n += 1
            cleaned = f"{base}_{n}"[:40]
        return cleaned


__all__ = ["ScheduleToXer"]
