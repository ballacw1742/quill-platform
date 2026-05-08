"""Synthetic procurement feeder.

Trickles vendor email confirmations + portal updates throughout the day.
A configurable fraction of POs slip ship dates over time, prompting the
Procurement Watch agent to flag CP impact.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import Any

from quill_mock_data.feeders import FeederEvent, render
from quill_mock_data.seed import build_pos


_UPDATE_KINDS = (
    "submittal_received",
    "manufacturing_started",
    "factory_test_passed",
    "shipping_scheduled",
    "shipped",
    "delay_notice",
    "delivery_confirmed",
)


def _ship_slip_weeks(rng: random.Random) -> int:
    # 50% no slip, 30% 1-2 weeks, 15% 3-5 weeks, 5% 6+ weeks
    r = rng.random()
    if r < 0.50:
        return 0
    if r < 0.80:
        return rng.randint(1, 2)
    if r < 0.95:
        return rng.randint(3, 5)
    return rng.randint(6, 12)


def _make_update(rng: random.Random, po: dict[str, Any]) -> dict[str, Any]:
    kind = rng.choice(_UPDATE_KINDS)
    slip = _ship_slip_weeks(rng) if kind == "delay_notice" else 0
    revised_ship = None
    if slip:
        agreed = datetime.fromisoformat(po["agreed_ship_date"]).date()
        revised_ship = (agreed + timedelta(weeks=slip)).isoformat()

    body_pool = {
        "submittal_received": "Submittal package received by our engineering. Reviewing for compliance.",
        "manufacturing_started": "Mfg release issued. Production now in our queue.",
        "factory_test_passed": "Factory acceptance test passed. Witness reports attached.",
        "shipping_scheduled": "Logistics confirmed. Carrier dispatch coordinated.",
        "shipped": "Shipment dispatched. Tracking attached. Expected arrival within window.",
        "delay_notice": ("Heads-up — supplier of long-lead component pushed delivery by "
                         f"{slip} week(s). Below is our revised plan."),
        "delivery_confirmed": "Delivery confirmed at site. Receiving signature attached.",
    }

    email = render(
        "vendor_email.j2",
        from_name=f"PM, {po['vendor']}",
        from_email=f"pm@{po['vendor'].lower().replace(' ', '').replace(',', '').replace('/', '-')}.com",
        subject=f"[{po['po_id']}] {kind.replace('_', ' ').title()}",
        date=datetime.now().strftime("%a, %d %b %Y %H:%M %Z"),
        greeting=rng.choice(["Hi team", "Hello procurement", "Good morning"]),
        po_id=po["po_id"],
        item=po["item"],
        quantity=po["quantity"],
        body=body_pool[kind],
        agreed_ship_date=po["agreed_ship_date"],
        revised_ship_date=revised_ship,
        action_required=("Confirm receipt and acknowledge revised milestone." if kind == "delay_notice" else None),
        vendor=po["vendor"],
    )

    return {
        "po_id": po["po_id"],
        "vendor": po["vendor"],
        "item": po["item"],
        "csi": po["csi"],
        "kind": kind,
        "agreed_ship_date": po["agreed_ship_date"],
        "revised_ship_date": revised_ship,
        "slip_weeks": slip,
        "cp_activity_refs": po.get("cp_activity_refs", []),
        "email_body": email,
        "received_at": datetime.utcnow().isoformat() + "Z",
    }


def tick(target_count: int | None = None, seed: int | None = None) -> list[FeederEvent]:
    rng = random.Random(seed)
    pos = build_pos()
    n = target_count if target_count is not None else rng.randint(1, 3)
    chosen = rng.sample(pos, k=min(n, len(pos)))
    events: list[FeederEvent] = []
    for po in chosen:
        update = _make_update(rng, po.__dict__)
        events.append(FeederEvent(
            kind="procurement.update",
            payload=update,
            source="procurement-feeder",
        ))
    return events
