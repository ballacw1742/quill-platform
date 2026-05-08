"""Bootstrap data: spec corpus, subcontractor roster, long-lead PO list, IMS (P6 XER).

Run via `quill-mock bootstrap`. Idempotent — writes to a local store
(./mock-data/_state/) and posts a project-bootstrap approval to the API
to anchor the audit chain on day zero.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from quill_mock_data.project import QPB1

log = structlog.get_logger(__name__)

STATE_DIR = Path(__file__).resolve().parent.parent / "_state"
STATE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Spec corpus — 12 representative CSI MasterFormat sections
# ---------------------------------------------------------------------------
SPEC_SECTIONS: list[dict[str, str]] = [
    {
        "section": "03 30 00",
        "title": "Cast-in-Place Concrete",
        "summary": "f'c=5000psi at 28d for foundations. Lap splices min 48d_b. Slump 4-6\".",
    },
    {
        "section": "05 12 00",
        "title": "Structural Steel Framing",
        "summary": "ASTM A992 Gr.50 wide flange. Bolts A325-N pretensioned. Camber per drawings.",
    },
    {
        "section": "07 84 00",
        "title": "Firestopping",
        "summary": "UL-listed assemblies for all rated penetrations. STI Specseal or approved equal.",
    },
    {
        "section": "21 13 13",
        "title": "Wet-Pipe Sprinkler Systems",
        "summary": "FM-200 backup in MV switch rooms. Hydraulic calc per NFPA 13. Pre-action in IT halls.",
    },
    {
        "section": "23 09 23",
        "title": "Direct-Digital Control System for HVAC",
        "summary": "BACnet/IP. Tridium Niagara framework. 100% redundant supervisory controllers.",
    },
    {
        "section": "23 64 16",
        "title": "Centrifugal Water Chillers",
        "summary": "2500-ton magnetic-bearing chillers, R-1234ze. AHRI 550/590 certified. N+1 redundancy.",
    },
    {
        "section": "23 81 23",
        "title": "Computer Room Air Conditioners",
        "summary": "CRAH units, EC fan, chilled-water coil. Variable airflow, 0.5\" w.c. plenum.",
    },
    {
        "section": "26 09 23",
        "title": "Lighting Control Devices",
        "summary": "DALI-2 protocol. Daylight harvesting in office areas. Emergency egress per NFPA 101.",
    },
    {
        "section": "26 13 13",
        "title": "Medium-Voltage Switchgear",
        "summary": "34.5kV class, ANSI C37.20. Vacuum interrupters, arc-resistant per IEEE C37.20.7.",
    },
    {
        "section": "26 23 00",
        "title": "Low-Voltage Switchgear",
        "summary": "480V, ANSI C37.20.1. Drawout breakers, 100% rated bus. Selectivity per IEEE 242.",
    },
    {
        "section": "26 32 13",
        "title": "Engine Generators",
        "summary": "3MW diesel, EPA Tier 4. 7 days fuel storage. Block heater + battery charger.",
    },
    {
        "section": "26 33 53",
        "title": "Static Uninterruptible Power Supply",
        "summary": "1.5MW modular UPS, 96% eta at 50%. Lithium-ion battery, 5-min runtime.",
    },
]


# ---------------------------------------------------------------------------
# Subcontractor roster
# ---------------------------------------------------------------------------
SUBS: list[dict[str, str]] = [
    {"name": "Atlas Concrete Group", "trade": "concrete", "csi": "03"},
    {"name": "Buckeye Reinforcing Steel", "trade": "rebar", "csi": "03"},
    {"name": "Cardinal Earthworks", "trade": "earthwork", "csi": "31"},
    {"name": "Helios Structural Steel", "trade": "structural_steel", "csi": "05"},
    {"name": "Vulcan Misc Metals", "trade": "misc_metals", "csi": "05"},
    {"name": "Northern Drywall & Acoustics", "trade": "drywall", "csi": "09"},
    {"name": "Apex Roofing Systems", "trade": "roofing", "csi": "07"},
    {"name": "Sentinel Firestop", "trade": "firestop", "csi": "07"},
    {"name": "Glassline Curtainwall", "trade": "curtainwall", "csi": "08"},
    {"name": "Trinity Mechanical", "trade": "hvac_piping", "csi": "23"},
    {"name": "Coldfront Chiller Plant LLC", "trade": "chiller_plant", "csi": "23"},
    {"name": "Skyline Sheetmetal", "trade": "sheetmetal_ductwork", "csi": "23"},
    {"name": "Bluewater Plumbing", "trade": "plumbing", "csi": "22"},
    {"name": "Inferno Fire Protection", "trade": "sprinkler", "csi": "21"},
    {"name": "Volt Power Inc", "trade": "electrical_high_voltage", "csi": "26"},
    {"name": "Crescent Electric", "trade": "electrical_low_voltage", "csi": "26"},
    {"name": "Quanta Conduit & Cable", "trade": "raceway", "csi": "26"},
    {"name": "Apogee Generators", "trade": "generator_install", "csi": "26"},
    {"name": "Helios UPS Services", "trade": "ups_install", "csi": "26"},
    {"name": "Forge Controls Integrators", "trade": "bms_controls", "csi": "23"},
    {"name": "Lattice Low-Voltage", "trade": "tele_data", "csi": "27"},
    {"name": "Sentry Access Systems", "trade": "security_access", "csi": "28"},
    {"name": "Pacific Painting Co", "trade": "paint", "csi": "09"},
    {"name": "Boreal Insulation", "trade": "insulation", "csi": "07"},
    {"name": "Granite Sitework Partners", "trade": "site_utilities", "csi": "33"},
]


# ---------------------------------------------------------------------------
# Long-lead procurement list — 30 items
# ---------------------------------------------------------------------------
def _po_id(idx: int) -> str:
    return f"PO-2026-{1000 + idx:04d}"


_PO_TEMPLATES: list[tuple[str, str, str, int, int]] = [
    # (item, vendor, csi, qty, base_lead_weeks)
    ("34.5kV MV switchgear lineup", "ABB", "26 13 13", 8, 64),
    ("480V LV switchgear lineup", "Schneider Electric", "26 23 00", 16, 52),
    ("3MW diesel generator", "Cummins Power Systems", "26 32 13", 24, 78),
    ("1.5MW modular UPS", "Vertiv", "26 33 53", 48, 60),
    ("2500-ton centrifugal chiller", "Trane Technologies", "23 64 16", 12, 70),
    ("Cooling tower module", "BAC (Baltimore Aircoil)", "23 65 00", 16, 48),
    ("Pump skid — primary CHW", "Armstrong Fluid Tech", "23 21 23", 8, 32),
    ("Pump skid — secondary CHW", "Armstrong Fluid Tech", "23 21 23", 8, 32),
    ("CRAH units (450 kW)", "Stulz", "23 81 23", 96, 38),
    ("Pad-mounted transformer 2500 kVA", "Eaton", "26 12 00", 24, 56),
    ("Generator paralleling switchgear", "ASCO", "26 36 00", 4, 60),
    ("Static transfer switch 4000A", "ASCO", "26 36 23", 12, 50),
    ("Lithium-ion battery cabinet", "EnerSys", "26 33 53", 96, 44),
    ("Air-cooled chiller (water-side econ)", "York / Johnson Controls", "23 64 19", 4, 50),
    ("DCIM platform license + appliances", "Schneider EcoStruxure", "23 09 23", 1, 28),
    ("BMS field controllers (lot)", "Distech Controls", "23 09 23", 200, 30),
    ("Variable frequency drives", "ABB", "26 29 23", 64, 36),
    ("Bus duct — 6000A", "Siemens", "26 25 00", 1200, 42),
    ("Fiber optic backbone (single-mode lot)", "Corning", "27 13 00", 1, 22),
    ("Structured cabling — Cat6A drops", "Panduit", "27 15 00", 24000, 18),
    ("Liebert iCOM controls", "Vertiv", "23 81 23", 96, 36),
    ("Fire-rated cable tray", "Cooper B-Line", "26 05 36", 4800, 24),
    ("Generator paralleling controls", "Woodward", "26 36 23", 4, 48),
    ("Diesel fuel polishing system", "Algae-X", "23 05 19", 4, 28),
    ("Roof curb and dunnage steel pkgs", "AISC fab — Kovach", "07 71 00", 16, 22),
    ("Pre-action sprinkler controllers", "Viking SupplyNet", "21 13 13", 32, 26),
    ("Lighting controls server", "Lutron Quantum", "26 09 23", 1, 24),
    ("Owner-furnished IT pods (white space)", "Schneider HyperPod", "27 11 00", 64, 36),
    ("Switchboard remote racking robot", "CBS ArcSafe", "26 23 00", 4, 32),
    ("FM-200 clean agent suppression", "Kidde", "21 22 00", 8, 28),
]


@dataclass
class POEntry:
    po_id: str
    item: str
    vendor: str
    csi: str
    quantity: int
    award_date: str
    agreed_ship_date: str
    revised_ship_date: str | None
    status: str  # awarded | submittal_under_review | manufacturing | shipping | received | slipped
    cp_activity_refs: list[str] = field(default_factory=list)


def build_pos(seed: int = 1742) -> list[POEntry]:
    rng = random.Random(seed)
    pos: list[POEntry] = []
    award_anchor = QPB1.construction_start - timedelta(days=180)
    for i, (item, vendor, csi, qty, lead_weeks) in enumerate(_PO_TEMPLATES):
        award = award_anchor + timedelta(days=rng.randint(-30, 30))
        ship = award + timedelta(weeks=lead_weeks + rng.randint(-3, 6))
        pos.append(
            POEntry(
                po_id=_po_id(i + 1),
                item=item,
                vendor=vendor,
                csi=csi,
                quantity=qty,
                award_date=award.isoformat(),
                agreed_ship_date=ship.isoformat(),
                revised_ship_date=None,
                status="awarded",
                cp_activity_refs=[f"A{1000 + (i * 17) % 4500:04d}"],
            )
        )
    return pos


# ---------------------------------------------------------------------------
# Simplified IMS — emit a minimal P6 XER file with ~500 activities
# ---------------------------------------------------------------------------
def build_ims_xer(activities_per_building: int = 125) -> str:
    """Emit a tiny but parseable subset of P6 XER format.

    Real XER is tab-separated with %T/%F/%R/%E rows. We produce just enough
    structure to be recognizable by P6 import (and our own dispatcher
    consumes via task descriptions, not full XER semantics).
    """
    lines: list[str] = []
    lines.append("ERMHDR\t8.3\t" + datetime.now().strftime("%Y-%m-%d") + "\tProject\tquill\tquill\tdbxDatabaseNoName\tProject Management\tUSD")
    lines.append("%T\tPROJECT")
    lines.append("%F\tproj_id\tproj_short_name\tplan_start_date\tplan_end_date")
    lines.append(f"%R\t1\t{QPB1.project_id}\t{QPB1.construction_start.isoformat()}\t{QPB1.substantial_completion.isoformat()}")
    lines.append("%T\tTASK")
    lines.append("%F\ttask_id\tproj_id\twbs_id\ttask_code\ttask_name\ttarget_drtn_hr_cnt\ttarget_start_date\ttarget_end_date")

    rng = random.Random(2026)
    activity_idx = 1000
    cursor = QPB1.construction_start
    for b in QPB1.buildings:
        for n in range(activities_per_building):
            duration_days = rng.randint(3, 28)
            start = cursor + timedelta(days=rng.randint(0, 600))
            end = start + timedelta(days=duration_days)
            phase = ("Site & Foundations", "Structure", "Skin", "Mechanical", "Electrical",
                     "Controls", "Test & Commissioning")[n // (activities_per_building // 7 or 1) % 7]
            name = f"{b.code} {phase} act {n+1:03d}"
            lines.append(
                f"%R\t{activity_idx}\t1\t1\tA{activity_idx:04d}\t{name}\t"
                f"{duration_days * 8}\t{start.isoformat()}\t{end.isoformat()}"
            )
            activity_idx += 1
    lines.append("%E")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
def _project_summary_payload(pos: list[POEntry]) -> dict[str, Any]:
    return {
        "project_id": QPB1.project_id,
        "name": QPB1.name,
        "address": QPB1.address,
        "buildings": [
            {
                "code": b.code,
                "name": b.name,
                "gross_sqft": b.gross_sqft,
                "it_load_mw": b.it_load_mw,
                "energization_target": b.energization_target.isoformat(),
            }
            for b in QPB1.buildings
        ],
        "construction_start": QPB1.construction_start.isoformat(),
        "substantial_completion": QPB1.substantial_completion.isoformat(),
        "long_lead_po_count": len(pos),
        "spec_section_count": len(SPEC_SECTIONS),
        "subcontractor_count": len(SUBS),
        "hyperscaler_reps": [r.name for r in QPB1.hyperscaler_reps],
    }


def write_state() -> dict[str, Path]:
    """Write all bootstrap artifacts to STATE_DIR. Returns paths written."""
    pos = build_pos()
    paths: dict[str, Path] = {}

    paths["spec"] = STATE_DIR / "spec_sections.json"
    paths["spec"].write_text(json.dumps(SPEC_SECTIONS, indent=2))

    paths["subs"] = STATE_DIR / "subcontractors.json"
    paths["subs"].write_text(json.dumps(SUBS, indent=2))

    paths["pos"] = STATE_DIR / "long_lead_pos.json"
    paths["pos"].write_text(json.dumps([asdict(p) for p in pos], indent=2))

    paths["ims"] = STATE_DIR / "ims.xer"
    paths["ims"].write_text(build_ims_xer())

    paths["project"] = STATE_DIR / "project.json"
    paths["project"].write_text(json.dumps(_project_summary_payload(pos), indent=2))

    log.info("seed.write_state.complete", paths={k: str(v) for k, v in paths.items()})
    return paths


def load_state() -> dict[str, Any]:
    """Load all bootstrap artifacts from STATE_DIR."""
    return {
        "spec_sections": json.loads((STATE_DIR / "spec_sections.json").read_text()) if (STATE_DIR / "spec_sections.json").exists() else SPEC_SECTIONS,
        "subcontractors": json.loads((STATE_DIR / "subcontractors.json").read_text()) if (STATE_DIR / "subcontractors.json").exists() else SUBS,
        "long_lead_pos": json.loads((STATE_DIR / "long_lead_pos.json").read_text()) if (STATE_DIR / "long_lead_pos.json").exists() else [asdict(p) for p in build_pos()],
        "project": json.loads((STATE_DIR / "project.json").read_text()) if (STATE_DIR / "project.json").exists() else _project_summary_payload(build_pos()),
    }
