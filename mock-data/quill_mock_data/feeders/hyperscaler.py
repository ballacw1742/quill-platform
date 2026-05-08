"""Synthetic hyperscaler-inbound feeder.

Models occasional spec addenda, drawing revisions, owner directives, and
RFI requests dropped into the inbound drop point. Exercises Inbound Ingest
classification.
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from quill_mock_data.feeders import FeederEvent
from quill_mock_data.project import QPB1
from quill_mock_data.seed import SPEC_SECTIONS

_INBOUND_TYPES = (
    "spec_addendum",
    "drawing_revision",
    "owner_directive",
    "rfi_request",
    "value_engineering_request",
    "milestone_update",
)


def _make_one(rng: random.Random, idx: int) -> dict[str, Any]:
    kind = rng.choice(_INBOUND_TYPES)
    rep = rng.choice(QPB1.hyperscaler_reps)
    spec = rng.choice(SPEC_SECTIONS)

    descriptions = {
        "spec_addendum": f"Addendum #{rng.randint(2,18)} to {spec['section']} {spec['title']} — clarifies redundancy requirements and updates qualified manufacturers list.",
        "drawing_revision": f"Drawing revision Rev-{rng.choice('CDEF')}: {rng.choice(['MV one-line', 'chiller plant flow', 'roof penetration plan', 'controls riser'])} updated. Supersedes prior issue.",
        "owner_directive": f"Owner directive {idx:03d}: proceed with {rng.choice(['adding fiber riser to BLDG3', 'paint color change in office areas', 'expanded access control to MV vaults'])}. Cost change request to follow.",
        "rfi_request": f"Owner-side question: please clarify how {spec['title'].lower()} will be commissioned in light of new {rng.choice(['heat-rejection strategy', 'redundancy class', 'load profile'])}.",
        "value_engineering_request": f"VE request VE-{idx:03d}: review alternatives to {rng.choice(['MV switchgear single-source', 'CRAH brand', 'lighting controls platform'])} for cost reduction.",
        "milestone_update": f"Hyperscaler updated milestone target for {rng.choice(['BLDG1 power-on', 'BLDG2 mech complete', 'BLDG3 white-space deliver'])} by {rng.randint(2,8)} weeks earlier — confirm impact.",
    }

    return {
        "inbound_id": f"HS-{idx:05d}",
        "kind": kind,
        "from_rep": rep.name,
        "from_email": rep.email,
        "subject": f"[{kind.replace('_', ' ').upper()}] {descriptions[kind][:60]}",
        "received_at": datetime.utcnow().isoformat() + "Z",
        "spec_section": spec["section"],
        "body": descriptions[kind],
        "attachments": [
            f"{kind}-{idx:05d}-attachment-{n}.pdf"
            for n in range(1, rng.randint(1, 4))
        ],
    }


def tick(target_count: int | None = None, seed: int | None = None) -> list[FeederEvent]:
    rng = random.Random(seed)
    n = target_count if target_count is not None else (1 if rng.random() < 0.7 else 0)
    base_idx = rng.randint(1000, 8999)
    events: list[FeederEvent] = []
    for i in range(n):
        events.append(FeederEvent(
            kind="hyperscaler.inbound",
            payload=_make_one(rng, base_idx + i),
            source="hyperscaler-feeder",
        ))
    return events
