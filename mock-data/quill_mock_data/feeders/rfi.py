"""Synthetic RFI feeder.

Posts 5–15 RFIs/day. Each RFI references the spec corpus + a drawing ID
+ a building + a discipline. ~10% are flagged "critical_path".
"""

from __future__ import annotations

import random
from typing import Any

from faker import Faker

from quill_mock_data.feeders import FeederEvent, render
from quill_mock_data.project import QPB1, building_codes
from quill_mock_data.seed import SPEC_SECTIONS, SUBS

_fake = Faker()
Faker.seed(1742)


_DISCIPLINES = (
    "structural", "architectural", "mechanical", "electrical", "plumbing",
    "fire_protection", "controls", "civil", "low_voltage",
)

_QUESTION_BANK = [
    "Confirm rebar lap length at column {grid}; field measured {a}\" but spec calls for {b}\".",
    "Drawing {drawing_id} shows duct routing through structural beam at {grid}. Coord with steel?",
    "Spec {spec} says {req} but submitted shop drawing shows {actual}. Which governs?",
    "Crew encountered unforeseen {obstacle} at {grid}. Need direction before proceeding.",
    "Conflict between architectural ceiling and mechanical plenum at {grid}; need RCP confirmation.",
    "MV switchgear ground bus per drawing differs from manufacturer standard. Approve deviation?",
    "Generator paralleling sequence per spec {spec} appears to conflict with controls narrative.",
    "Owner-furnished IT pod tie-in at {grid}: confirm cable tray fill and bend radius.",
    "Fire-rated penetration at {grid}: spec {spec} firestop assembly not UL-listed for this combo.",
    "Cooling tower piping pressure test medium: spec calls for water but ambient is freezing. Glycol OK?",
]


def _drawing_id(rng: random.Random, discipline: str, building: str) -> str:
    prefix = {
        "structural": "S", "architectural": "A", "mechanical": "M",
        "electrical": "E", "plumbing": "P", "fire_protection": "FP",
        "controls": "T", "civil": "C", "low_voltage": "LV",
    }.get(discipline, "G")
    return f"{building}-{prefix}{rng.randint(100, 899)}"


def _make_one(rng: random.Random, idx: int) -> dict[str, Any]:
    spec = rng.choice(SPEC_SECTIONS)
    discipline = rng.choice(_DISCIPLINES)
    building = rng.choice(building_codes())
    sub = rng.choice([s for s in SUBS if s["csi"] in spec["section"][:2] or rng.random() < 0.3])
    grid = f"{rng.choice('ABCDEFG')}-{rng.randint(1, 24)}"
    drawing_id = _drawing_id(rng, discipline, building)

    rfi_id = f"RFI-{building}-{idx:04d}"
    priority = rng.choices(
        ["low", "normal", "high", "critical_path"],
        weights=[0.10, 0.55, 0.25, 0.10],
        k=1,
    )[0]

    template_q = rng.choice(_QUESTION_BANK)
    question = template_q.format(
        grid=grid,
        drawing_id=drawing_id,
        spec=spec["section"],
        req="f'c=5000 psi at 28d",
        actual="f'c=4500 psi mix design submitted",
        a=str(rng.randint(36, 44)),
        b=str(rng.randint(48, 60)),
        obstacle=rng.choice(["abandoned utility line", "buried boulder", "groundwater", "rock outcrop"]),
    )

    body = render(
        "rfi_body.j2",
        rfi_id=rfi_id,
        subject=f"{spec['title']} — {discipline} clarification",
        building=building,
        level=f"L{rng.randint(0, 3)}",
        gridline=grid,
        discipline=discipline,
        drawing_id=drawing_id,
        spec_section=spec["section"],
        spec_title=spec["title"],
        submitter_name=_fake.name(),
        submitter_role=rng.choice(["Foreman", "Project Engineer", "Superintendent", "Field Engineer"]),
        subcontractor=sub["name"],
        priority=priority,
        question=question,
        context=f"Issue surfaced during {rng.choice(['layout', 'rough-in', 'inspection walk', 'submittal review'])}. Production at risk if unresolved by {_fake.date_between('+3d','+10d')}.",
        proposed_resolution=rng.choice([
            "Field verify and document — confirm by EOR.",
            "Issue ASI to update drawing; cost-neutral.",
            "Substitute equivalent product per spec equal-or-better clause.",
            "Owner direction required — escalate to hyperscaler rep.",
        ]),
        extra_attachments=[f"{drawing_id}-detail-{rng.randint(1,9)}.pdf"] if rng.random() < 0.4 else [],
    )

    return {
        "rfi_id": rfi_id,
        "subject": f"{spec['title']} — {discipline} clarification",
        "building": building,
        "discipline": discipline,
        "drawing_id": drawing_id,
        "spec_section": spec["section"],
        "subcontractor": sub["name"],
        "priority": priority,
        "body": body,
        "submitted_at": None,  # filled at emit
    }


def tick(target_count: int | None = None, seed: int | None = None) -> list[FeederEvent]:
    """Generate a batch of synthetic RFIs.

    With APScheduler running this every ~hour during business hours,
    target_count of 1 produces ~10/day. Tests pass an explicit value.
    """
    rng = random.Random(seed)
    n = target_count if target_count is not None else rng.randint(1, 2)
    base_idx = rng.randint(100, 9000)
    events: list[FeederEvent] = []
    for i in range(n):
        rfi = _make_one(rng, base_idx + i)
        events.append(FeederEvent(kind="rfi.new", payload=rfi, source="rfi-feeder"))
    return events
