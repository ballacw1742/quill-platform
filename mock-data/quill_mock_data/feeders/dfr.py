"""Synthetic DFR (Daily Field Report) feeder.

Each business day at 7am ET, 4 superintendents (one per building) post a
narrative DFR. The Synthesizer agent later turns these into P6 progress
proposals.
"""

from __future__ import annotations

import random
from datetime import date
from typing import Any

from quill_mock_data.feeders import FeederEvent, render
from quill_mock_data.project import QPB1, building_codes, superintendent_for


_DISCIPLINES_FOR_DFR = (
    "earthwork", "concrete", "rebar", "structural_steel",
    "mep_rough", "drywall", "controls", "commissioning",
)

_WEATHER_CONDITIONS = ("clear", "partly cloudy", "overcast", "light rain", "scattered showers", "windy")


def _activity_progress_row(rng: random.Random, building: str) -> dict[str, Any]:
    activity_id = f"A{rng.randint(1000, 5500):04d}"
    total = rng.randint(50, 600)
    installed = rng.randint(0, total)
    pct = round(100.0 * installed / total, 1) if total else 0.0
    activity = rng.choice([
        f"{building} mat foundation pour",
        f"{building} CMU shaft walls",
        f"{building} roof deck installation",
        f"{building} CRAH unit set",
        f"{building} MV conduit rough-in",
        f"{building} chiller piping",
        f"{building} bus duct hang",
        f"{building} fire-stop penetrations",
    ])
    uom = rng.choice(["CY", "EA", "LF", "SF", "TON"])
    return {
        "activity": activity,
        "activity_id": activity_id,
        "installed": installed,
        "total": total,
        "pct": pct,
        "uom": uom,
    }


def _make_one(rng: random.Random, building: str, report_date: date) -> dict[str, Any]:
    super_name = superintendent_for(building)
    headcount = rng.randint(60, 240)
    quantities = [_activity_progress_row(rng, building) for _ in range(rng.randint(3, 6))]

    delays_pool = [
        "Pour delayed 2 hr — pump truck arrived late.",
        "RFI {rfi} blocked rebar tie at gridline {grid} — awaiting response.",
        "Crane move impacted CMU production — recovered by lunch.",
        "Owner walk pushed ironworker tie-in by 1 hr.",
        "Fuel delivery for generator commissioning slipped to tomorrow.",
    ]
    delays = []
    if rng.random() < 0.55:
        delays.append(rng.choice(delays_pool).format(
            rfi=f"RFI-{building}-{rng.randint(100, 9000):04d}",
            grid=f"{rng.choice('ABCDEFG')}-{rng.randint(1, 24)}",
        ))

    body = render(
        "dfr_narrative.j2",
        date=report_date.isoformat(),
        building=building,
        super_name=super_name,
        weather=rng.choice(_WEATHER_CONDITIONS),
        high_f=rng.randint(45, 92),
        low_f=rng.randint(28, 70),
        wind=rng.randint(3, 22),
        headcount=headcount,
        disciplines=rng.sample(_DISCIPLINES_FOR_DFR, k=rng.randint(3, 6)),
        hours_worked=headcount * 8 + rng.randint(-30, 60),
        work_done=rng.sample([
            f"Completed {q['activity']} ({q['pct']}%)" for q in quantities
        ], k=min(len(quantities), 4)),
        quantities=quantities,
        delays=delays,
        ptp_signed=headcount,
        near_misses=rng.choices([0, 0, 0, 1], k=1)[0],
        recordables=0 if rng.random() > 0.02 else 1,
        visitors=[
            "Hyperscaler OAC walk — Marcus Doyle 09:30",
        ] if rng.random() < 0.3 else ["No site visitors of note."],
        lookahead=[
            f"Tomorrow: continue {quantities[0]['activity']}",
            "Next 48h: prep for inspection on " + rng.choice(["MV gear", "chiller piping", "fire-stop"]),
            "Watch: weather forecast — "
            + rng.choice(["clear", "rain Thursday PM", "wind advisory midweek"]),
        ],
    )

    return {
        "dfr_id": f"DFR-{building}-{report_date.isoformat()}",
        "building": building,
        "report_date": report_date.isoformat(),
        "superintendent": super_name,
        "headcount": headcount,
        "quantities": quantities,
        "delays": delays,
        "narrative": body,
    }


def tick(report_date: date | None = None, buildings: list[str] | None = None,
         seed: int | None = None) -> list[FeederEvent]:
    rng = random.Random(seed)
    today = report_date or date.today()
    bldgs = buildings or building_codes()
    return [
        FeederEvent(kind="dfr.new", payload=_make_one(rng, b, today), source="dfr-feeder")
        for b in bldgs
    ]
