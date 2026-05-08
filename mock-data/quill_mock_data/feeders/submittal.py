"""Synthetic submittal feeder.

Posts 3–8 submittals/day. Some are deliberately non-conforming so the
Submittal Spec Validator has something to flag.
"""

from __future__ import annotations

import random
from typing import Any

from faker import Faker

from quill_mock_data.feeders import FeederEvent
from quill_mock_data.project import building_codes
from quill_mock_data.seed import SPEC_SECTIONS, SUBS

_fake = Faker()
Faker.seed(2026)


_PACKAGE_TYPES = (
    "product_data", "shop_drawings", "samples", "mix_design",
    "qualifications", "test_reports", "certificates", "operation_manuals",
)


def _conforming_payload(rng: random.Random, spec: dict[str, str]) -> dict[str, Any]:
    return {"compliant": True, "deltas": []}


def _non_conforming_payload(rng: random.Random, spec: dict[str, str]) -> dict[str, Any]:
    deltas = []
    section = spec["section"]
    if section.startswith("03"):
        deltas.append({"attr": "compressive_strength_psi", "spec": 5000, "submitted": rng.choice([3500, 4000, 4500])})
    elif section.startswith("23 64"):
        deltas.append({"attr": "refrigerant", "spec": "R-1234ze", "submitted": rng.choice(["R-134a", "R-410A"])})
        deltas.append({"attr": "AHRI_550_590", "spec": "certified", "submitted": "pending"})
    elif section.startswith("26 13"):
        deltas.append({"attr": "arc_resistance", "spec": "IEEE C37.20.7", "submitted": "not_listed"})
    elif section.startswith("26 32"):
        deltas.append({"attr": "EPA_tier", "spec": "Tier 4 Final", "submitted": rng.choice(["Tier 3", "Tier 2"])})
    elif section.startswith("26 33"):
        deltas.append({"attr": "battery_runtime_min", "spec": 5, "submitted": rng.choice([2, 3])})
    else:
        deltas.append({"attr": "manufacturer_certification", "spec": "current", "submitted": "expired"})
    return {"compliant": False, "deltas": deltas}


def _make_one(rng: random.Random, idx: int) -> dict[str, Any]:
    spec = rng.choice(SPEC_SECTIONS)
    sub = rng.choice([s for s in SUBS if s["csi"] in spec["section"][:2] or rng.random() < 0.2])
    building = rng.choice(building_codes())
    submittal_id = f"SUB-{building}-{idx:04d}"
    package = rng.choice(_PACKAGE_TYPES)

    is_non_conforming = rng.random() < 0.35
    contents = (_non_conforming_payload(rng, spec) if is_non_conforming
                else _conforming_payload(rng, spec))

    return {
        "submittal_id": submittal_id,
        "package_type": package,
        "spec_section": spec["section"],
        "spec_title": spec["title"],
        "subcontractor": sub["name"],
        "building": building,
        "submitted_by": _fake.name(),
        "manufacturer": _fake.company(),
        "model_number": f"{rng.choice('ABCDEFG')}{rng.randint(1000,9999)}-{rng.choice(['X','M','Q'])}",
        "contents": contents,
        "is_non_conforming_seed": is_non_conforming,
    }


def tick(target_count: int | None = None, seed: int | None = None) -> list[FeederEvent]:
    rng = random.Random(seed)
    n = target_count if target_count is not None else rng.randint(1, 2)
    base_idx = rng.randint(100, 9000)
    events: list[FeederEvent] = []
    for i in range(n):
        events.append(FeederEvent(
            kind="submittal.new",
            payload=_make_one(rng, base_idx + i),
            source="submittal-feeder",
        ))
    return events
