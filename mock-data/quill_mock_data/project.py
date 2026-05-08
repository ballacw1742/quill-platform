"""QPB1 — Quill Pilot Build 1.

Fictional $10B / 1.7 GW / 4-building hyperscale data center campus.
Ground-up construction starts 2026-06-23, ~30 month delivery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Building:
    code: str
    name: str
    gross_sqft: int
    it_load_mw: int
    energization_target: date


@dataclass(frozen=True)
class HyperscalerRep:
    name: str
    title: str
    email: str


@dataclass(frozen=True)
class ProjectMeta:
    project_id: str
    name: str
    address: str
    site_acreage: int
    total_value_usd: int
    total_it_load_mw: int
    construction_start: date
    substantial_completion: date
    buildings: tuple[Building, ...]
    hyperscaler_reps: tuple[HyperscalerRep, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# QPB1 — the canonical fictional project
# ---------------------------------------------------------------------------
QPB1 = ProjectMeta(
    project_id="QPB1",
    name="Quill Pilot Build 1",
    address="14000 Mink Hollow Rd, New Albany, OH 43054",
    site_acreage=420,
    total_value_usd=10_000_000_000,
    total_it_load_mw=1700,
    construction_start=date(2026, 6, 23),
    substantial_completion=date(2028, 12, 22),
    buildings=(
        Building("BLDG1", "QPB1 Building 1 — North Hall", 480_000, 425, date(2028, 4, 1)),
        Building("BLDG2", "QPB1 Building 2 — East Hall", 480_000, 425, date(2028, 6, 1)),
        Building("BLDG3", "QPB1 Building 3 — South Hall", 480_000, 425, date(2028, 9, 1)),
        Building("BLDG4", "QPB1 Building 4 — West Hall", 480_000, 425, date(2028, 12, 1)),
    ),
    hyperscaler_reps=(
        HyperscalerRep("Marcus Doyle", "Senior Construction PM", "marcus.doyle@hyperscaler-mock.com"),
        HyperscalerRep("Priya Raman", "Owner Mechanical Lead", "priya.raman@hyperscaler-mock.com"),
        HyperscalerRep("Ethan Cho", "Owner Electrical Lead", "ethan.cho@hyperscaler-mock.com"),
        HyperscalerRep("Sara Lindqvist", "Commissioning Manager", "sara.lindqvist@hyperscaler-mock.com"),
        HyperscalerRep("Trevor Wallace", "Owner Schedule & Cost", "trevor.wallace@hyperscaler-mock.com"),
    ),
)


def building_codes() -> list[str]:
    return [b.code for b in QPB1.buildings]


def superintendent_for(building_code: str) -> str:
    """Stable mapping of building → superintendent name."""
    mapping = {
        "BLDG1": "Ricardo Alvarez",
        "BLDG2": "Tasha Berkowitz",
        "BLDG3": "Devon Okafor",
        "BLDG4": "Lila Chen",
    }
    return mapping.get(building_code, "Unknown Super")
