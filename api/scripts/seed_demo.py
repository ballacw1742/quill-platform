"""Seed a coherent, wipeable demo dataset across every Quill module.

Sprint 3 (G4). One company story, mutually consistent numbers:

  * Sites   — 2 evaluated sites (DataSite DB, optional via DATASITE_DATABASE_URL)
  * Projects — "Ridgeline DC-2" mid-flight (milestones, log, budget lines,
               RFIs/submittals as requests + approvals) and completed
               "Blue Creek DC-1" (history for the live campus)
  * Operations — "Blue Creek Campus" live: 1 investigating P2 + 2 resolved
               incidents, 7 days of PUE/power/uptime metrics, monitoring agents
  * Pipeline — 6 accounts / 5 deals (2 early, 1 negotiating, 1 won $18M, 1 lost)
  * Customers — 3 customer accounts (healthy / at-risk / new) with tickets
  * Finance  — invoices (paid + aging AR), budget lines that sum to the
               Ridgeline budget, equipment-capex-consistent committed values
  * Compliance — obligations / regulatory / insurance / SOC 2 checklist
  * Approvals — 4 pending items across lanes 1/2/3 (audit-chained)

Marker strategy
---------------
Every row this script creates in the Quill DB has a primary key of the form
``demo-<31 hex chars>`` (deterministic sha1 of a slug). Real rows are uuid4
strings, so ``id LIKE 'demo-%'`` is an exact, safe wipe scope. DataSite rows
(UUID pk column) use fixed uuid5 ids listed in DEMO_SITE_UUIDS and carry
``"demo_seed": true`` inside record_json.

Idempotency: rows are upserted by their deterministic id — re-running
refreshes fields without duplicating rows. Audit-log entries are append-only
by design and are never deleted (a ``demo.seed.wiped`` event is recorded on
wipe instead).

Usage (run from the ``api/`` directory so ``app`` is importable):

    DATABASE_URL=... python -m scripts.seed_demo            # seed / refresh
    DATABASE_URL=... python -m scripts.seed_demo --wipe     # remove demo rows
    DATABASE_URL=... python -m scripts.seed_demo --counts   # demo-row counts

Optional env:
    DATASITE_DATABASE_URL  — also seed/wipe 2 demo sites in the DataSite DB
    DEMO_OWNER_EMAIL       — own demo projects/requests as this user
                             (default: owner of the real Adams Fork project,
                             else first owner-role user, else a demo user)

This script never modifies existing rows: not users, not the real Adams Fork
site/project, not existing approvals or the audit chain. Append-only.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta

from app import db as db_module
from app.enums import Lane, Priority, TargetSystem, UserRole
from app.models import ApprovalItem, User
from app.models_compliance import (
    ComplianceChecklist,
    ComplianceChecklistItem,
    ContractObligation,
    InsurancePolicy,
    RegulatoryItem,
)
from app.models_customers import AccountNote, SupportTicket
from app.models_finance import BudgetLine, Invoice
from app.models_operations import (
    Campus,
    CampusIncident,
    CampusMetric,
    CampusMonitoringAgent,
)
from app.models_pipeline import Account, Deal, DealActivity
from app.models_projects import Project, ProjectLogEntry, ProjectMilestone
from app.models_requests import RequestRecord
from app.models_supply_chain import Equipment, Vendor
from app.security import hash_password
from app.services.approvals import compute_sla_due, required_approvers_for_lane
from app.services.audit import record_event
from sqlalchemy import delete, func, select

# ---------------------------------------------------------------------------
# Constants — real prod rows we must never touch (referenced, not modified)
# ---------------------------------------------------------------------------

ADAMS_FORK_SITE_ID = "0786ab95-4b2d-4415-ae2a-540900f0fc12"
ADAMS_FORK_PROJECT_ID = "4e0f7207-6fff-494f-a069-55fad0764cc2"

DEMO_PREFIX = "demo-"


def demo_id(slug: str) -> str:
    """Deterministic 36-char id: 'demo-' + 31 hex chars. Exact wipe scope."""
    digest = hashlib.sha1(f"quill-demo:{slug}".encode()).hexdigest()[:31]
    return f"{DEMO_PREFIX}{digest}"


def demo_site_uuid(slug: str) -> str:
    """Deterministic UUID for DataSite rows (UUID pk column can't be prefixed)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"quill-demo:{slug}"))


DEMO_SITE_UUIDS = {
    "site-jackson": demo_site_uuid("site-jackson"),
    "site-berkeley": demo_site_uuid("site-berkeley"),
}

# ---------------------------------------------------------------------------
# Wipe scope — every Quill table the seed writes to, children first
# ---------------------------------------------------------------------------

DEMO_TABLES = [
    DealActivity,
    SupportTicket,
    AccountNote,
    Invoice,
    Deal,
    Account,
    CampusMetric,
    CampusIncident,
    CampusMonitoringAgent,
    Campus,
    ProjectMilestone,
    ProjectLogEntry,
    BudgetLine,
    Equipment,
    Vendor,
    ComplianceChecklistItem,
    ComplianceChecklist,
    ContractObligation,
    RegulatoryItem,
    InsurancePolicy,
    ApprovalItem,
    RequestRecord,
    Project,
    User,
]


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Upsert helper — deterministic id, no duplicate rows on re-run
# ---------------------------------------------------------------------------

async def upsert(session, model, slug: str, **fields):
    """Insert or refresh a demo row identified by demo_id(slug)."""
    pk = demo_id(slug)
    obj = await session.get(model, pk)
    if obj is None:
        obj = model(id=pk, **fields)
        session.add(obj)
        created = True
    else:
        for key, value in fields.items():
            setattr(obj, key, value)
        created = False
    return obj, created


# ---------------------------------------------------------------------------
# Owner resolution — reference (never modify) an existing user
# ---------------------------------------------------------------------------

async def resolve_owner_id(session) -> str:
    email = os.environ.get("DEMO_OWNER_EMAIL", "").strip()
    if email:
        row = (await session.execute(select(User).where(User.email == email))).scalars().first()
        if row is None:
            raise SystemExit(f"DEMO_OWNER_EMAIL={email!r} not found in users table")
        print(f"owner: {row.email} (via DEMO_OWNER_EMAIL)")
        return row.id

    adams = await session.get(Project, ADAMS_FORK_PROJECT_ID)
    if adams is not None:
        print(f"owner: user of Adams Fork project ({adams.user_id})")
        return adams.user_id

    row = (
        await session.execute(
            select(User).where(User.role == UserRole.OWNER.value).order_by(User.created_at)
        )
    ).scalars().first()
    if row is not None:
        print(f"owner: first owner-role user {row.email}")
        return row.id

    # Local dev fallback only — a demo-tagged user, removed by --wipe.
    user, created = await upsert(
        session,
        User,
        "user-owner",
        email="demo-owner@quill.local",
        display_name="Demo Owner",
        role=UserRole.OWNER.value,
        password_hash=hash_password("demo-owner-password"),
    )
    await session.flush()
    print(f"owner: created demo user {user.email} (local dev fallback)")
    return user.id


# ---------------------------------------------------------------------------
# Seed sections
# ---------------------------------------------------------------------------

async def seed_pipeline(session, today: date) -> None:
    campus_id = demo_id("campus-bluecreek")
    project_ridgeline = demo_id("project-ridgeline")

    accounts = [
        ("acct-helios", dict(
            name="Helios Compute Inc.", type="customer", industry="AI / Machine Learning",
            website="https://helioscompute.example.com", hq_city="San Jose", hq_state="CA",
            primary_contact_name="Dana Whitfield", primary_contact_email="dana.whitfield@helioscompute.example.com",
            campus_id=campus_id,
            notes="demo-seed: anchor AI training customer at Blue Creek Campus.")),
        ("acct-voltaic", dict(
            name="Voltaic AI Labs", type="customer", industry="AI Research",
            website="https://voltaic.example.com", hq_city="Austin", hq_state="TX",
            primary_contact_name="Priya Raman", primary_contact_email="priya@voltaic.example.com",
            campus_id=campus_id,
            notes="demo-seed: migrated legacy colo contract (pre-CRM); at-risk — open P1/P2 tickets.")),
        ("acct-northbeam", dict(
            name="Northbeam Data Systems", type="customer", industry="Enterprise SaaS",
            website="https://northbeam.example.com", hq_city="Columbus", hq_state="OH",
            primary_contact_name="Marcus Bell", primary_contact_email="mbell@northbeam.example.com",
            notes="demo-seed: newly onboarded customer; expansion deal in pipeline.")),
        ("acct-cirrus", dict(
            name="Cirrus Robotics", type="prospect", industry="Robotics",
            hq_city="Boston", hq_state="MA",
            primary_contact_name="Elena Sokolova", primary_contact_email="elena@cirrusrobotics.example.com",
            notes="demo-seed: early prospect — simulation cluster pilot.")),
        ("acct-atlas", dict(
            name="Atlas Grid Partners", type="prospect", industry="Hyperscale Cloud",
            hq_city="Charlotte", hq_state="NC",
            primary_contact_name="Rob Tanaka", primary_contact_email="rtanaka@atlasgrid.example.com",
            notes="demo-seed: negotiating anchor lease at Ridgeline DC-2.")),
        ("acct-meridian", dict(
            name="Meridian Cloud Services", type="prospect", industry="Cloud Infrastructure",
            hq_city="Denver", hq_state="CO",
            primary_contact_name="Sofia Reyes", primary_contact_email="sreyes@meridiancloud.example.com",
            notes="demo-seed: lost multi-region colo deal.")),
    ]
    for slug, fields in accounts:
        await upsert(session, Account, slug, **fields)

    deals = [
        ("deal-helios-won", dict(
            account_id=demo_id("acct-helios"),
            name="Helios — Blue Creek AI Training Capacity",
            stage="won", value_usd=18_000_000.0, mw_required=24.0, workload_type="ai_hpc",
            probability_pct=100, expected_close=today - timedelta(days=62),
            campus_id=campus_id,
            notes="demo-seed: closed-won; 24 MW AI training capacity at Blue Creek. Drives ARR.")),
        ("deal-atlas-neg", dict(
            account_id=demo_id("acct-atlas"),
            name="Atlas Grid — Ridgeline DC-2 Anchor Lease",
            stage="negotiating", value_usd=12_500_000.0, mw_required=15.0, workload_type="hyperscale",
            probability_pct=70, expected_close=today + timedelta(days=45),
            project_id=project_ridgeline,
            notes="demo-seed: anchor tenant lease for Ridgeline DC-2, in redlines.")),
        ("deal-northbeam-qual", dict(
            account_id=demo_id("acct-northbeam"),
            name="Northbeam — Edge Expansion",
            stage="qualified", value_usd=6_800_000.0, mw_required=8.0, workload_type="enterprise_colo",
            probability_pct=40, expected_close=today + timedelta(days=90),
            notes="demo-seed: expansion for a new customer.")),
        ("deal-cirrus-pros", dict(
            account_id=demo_id("acct-cirrus"),
            name="Cirrus Robotics — Sim Cluster Pilot",
            stage="prospect", value_usd=4_200_000.0, mw_required=6.0, workload_type="ai_hpc",
            probability_pct=15, expected_close=today + timedelta(days=120),
            notes="demo-seed: early-stage pilot conversation.")),
        ("deal-meridian-lost", dict(
            account_id=demo_id("acct-meridian"),
            name="Meridian — Multi-Region Colo",
            stage="lost", value_usd=9_000_000.0, mw_required=12.0, workload_type="enterprise_colo",
            probability_pct=0, expected_close=today - timedelta(days=20),
            lost_reason="Selected a competing Ashburn site — price and delivery timeline.",
            notes="demo-seed: closed-lost.")),
    ]
    for slug, fields in deals:
        await upsert(session, Deal, slug, **fields)

    activities = [
        ("act-helios-1", "deal-helios-won", "contract_sent", "MSA + capacity order executed; countersigned by Helios legal."),
        ("act-helios-2", "deal-helios-won", "note", "Kickoff complete — capacity energized at Blue Creek, billing started."),
        ("act-atlas-1", "deal-atlas-neg", "meeting", "Redline session on lease exhibit B (power pass-through)."),
        ("act-atlas-2", "deal-atlas-neg", "proposal_sent", "Revised anchor-lease term sheet sent (15 MW, 10-yr)."),
        ("act-northbeam-1", "deal-northbeam-qual", "call", "Capacity-planning call; 8 MW target confirmed for edge expansion."),
        ("act-cirrus-1", "deal-cirrus-pros", "email", "Intro email + Blue Creek case study sent."),
        ("act-meridian-1", "deal-meridian-lost", "note", "Loss review: beaten on delivered price/kW and Q3 availability."),
    ]
    for slug, deal_slug, kind, summary in activities:
        await upsert(
            session, DealActivity, slug,
            deal_id=demo_id(deal_slug), activity_type=kind,
            summary=f"demo-seed: {summary}", created_by="demo-seed",
        )


async def seed_operations(session, now: datetime) -> None:
    campus, _ = await upsert(
        session, Campus, "campus-bluecreek",
        project_id=demo_id("project-bluecreek"),
        name="Blue Creek Campus",
        address="2200 Blue Creek Industrial Pkwy, New Albany, OH 43054",
        mw_capacity=48.0, mw_live=36.0, status="live",
        pue_target=1.25, pue_current=1.21, uptime_pct=99.982, power_mw_current=31.4,
        notes="demo-seed: live campus serving Helios Compute + Voltaic AI Labs.",
    )

    incidents = [
        ("inc-chiller", dict(
            severity="P2", title="Chiller plant loop pressure anomaly — CH-3",
            description="Secondary loop differential pressure trending 12% above baseline on chiller 3.",
            status="investigating",
            impact="No customer impact; cooling plant remains N+1.",
            opened_at=now - timedelta(hours=6),
            created_by="demo-seed")),
        ("inc-feed-a", dict(
            severity="P1", title="Utility feed A transfer failure during storm",
            description="ATS-2 failed first transfer attempt during utility disturbance; retransfer succeeded.",
            status="resolved",
            impact="No customer-facing downtime — redundant feed and generators absorbed the event.",
            opened_at=now - timedelta(days=9),
            resolved_at=now - timedelta(days=9) + timedelta(hours=3),
            rca_notes="Worn ATS-2 control relay replaced; fleet-wide relay inspection scheduled.",
            created_by="demo-seed")),
        ("inc-bms", dict(
            severity="P3", title="BMS telemetry dropout — data hall B sensors",
            description="15-minute telemetry gap from hall B environmental sensors after firmware push.",
            status="resolved",
            impact="Monitoring visibility only; no environmental excursion.",
            opened_at=now - timedelta(days=15),
            resolved_at=now - timedelta(days=15) + timedelta(hours=1),
            rca_notes="Firmware rollback; vendor patch validated in staging before re-push.",
            created_by="demo-seed")),
    ]
    for slug, fields in incidents:
        await upsert(session, CampusIncident, slug, campus_id=campus.id, **fields)

    # 7 days of metrics; latest values match the campus snapshot fields.
    pue_series = [1.24, 1.23, 1.23, 1.22, 1.22, 1.21, 1.21]
    power_series = [29.8, 30.1, 30.6, 30.9, 31.2, 31.3, 31.4]
    for day_offset in range(7):
        recorded = now - timedelta(days=6 - day_offset)
        await upsert(
            session, CampusMetric, f"metric-pue-{day_offset}",
            campus_id=campus.id, metric_type="pue",
            value=pue_series[day_offset], unit=None, recorded_at=recorded,
        )
        await upsert(
            session, CampusMetric, f"metric-power-{day_offset}",
            campus_id=campus.id, metric_type="power_mw",
            value=power_series[day_offset], unit="MW", recorded_at=recorded,
        )
    await upsert(
        session, CampusMetric, "metric-uptime-0",
        campus_id=campus.id, metric_type="uptime_pct",
        value=99.982, unit="%", recorded_at=now - timedelta(hours=1),
    )

    agents = [
        ("mon-power", "power-monitor", "Power Chain Monitor", "power"),
        ("mon-cooling", "cooling-monitor", "Cooling Plant Monitor", "cooling"),
        ("mon-network", "network-monitor", "Network Fabric Monitor", "network"),
    ]
    for slug, key, name, kind in agents:
        await upsert(
            session, CampusMonitoringAgent, slug,
            campus_id=campus.id, agent_key=key, name=name,
            agent_type=kind, status="active",
        )


async def seed_projects(session, owner_id: str, now: datetime, today: date) -> None:
    await upsert(
        session, Project, "project-ridgeline",
        user_id=owner_id,
        name="Ridgeline DC-2",
        address="8821 State Route 32, Jackson, OH 45640 (Jackson County)",
        site_id=DEMO_SITE_UUIDS["site-jackson"],
        site_score=82.4, site_verdict="strong_recommend",
        workload_type="hyperscale",
        phase="construction", status="active",
        budget_usd=120_000_000.0, committed_usd=86_500_000.0, forecast_usd=124_500_000.0,
        notes="demo-seed: mid-flight build; forecast running $4.5M over budget (steel + switchgear).",
    )
    await upsert(
        session, Project, "project-bluecreek",
        user_id=owner_id,
        name="Blue Creek DC-1",
        address="2200 Blue Creek Industrial Pkwy, New Albany, OH 43054",
        workload_type="ai_hpc",
        phase="turnover", status="complete",
        budget_usd=95_000_000.0, committed_usd=94_200_000.0, forecast_usd=94_200_000.0,
        notes="demo-seed: delivered project; promoted to Blue Creek Campus (live).",
    )

    ridgeline = demo_id("project-ridgeline")
    milestones = [
        ("ms-site-control", "Site control executed", today - timedelta(days=210), now - timedelta(days=205)),
        ("ms-permits", "Building + air permits issued", today - timedelta(days=120), now - timedelta(days=118)),
        ("ms-fiber-duct", "Fiber duct bank complete", today - timedelta(days=6), None),  # overdue
        ("ms-steel", "Structural steel topping out", today + timedelta(days=20), None),
        ("ms-switchgear", "MV switchgear energization", today + timedelta(days=75), None),
        ("ms-backfeed", "Substation backfeed available", today + timedelta(days=120), None),
    ]
    for slug, name, due, completed in milestones:
        await upsert(
            session, ProjectMilestone, slug,
            project_id=ridgeline, name=name,
            description=f"demo-seed milestone: {name}",
            due_date=due, completed_at=completed,
        )

    log_entries = [
        ("log-rfi-231", "issue",
         "RFI-RDG-0231 raised: confirm rebar lap length at grid C-7 (Spec 03 30 00 §2.4). Routed to structural EOR."),
        ("log-sub-118", "issue",
         "Submittal SUB-RDG-0118 (MV switchgear arc-flash study) returned — revise and resubmit."),
        ("log-steel", "general",
         "Steel erection 68% complete; crane 2 demobilizes end of month."),
        ("log-duct-slip", "issue",
         "Fiber duct bank slipped 6 days — rock excavation on the north run."),
        ("log-decision-gen", "decision",
         "Approved alternate generator radiator supplier to protect delivery window."),
    ]
    for slug, kind, text in log_entries:
        await upsert(
            session, ProjectLogEntry, slug,
            project_id=ridgeline, user_id=owner_id,
            entry_type=kind, text=f"demo-seed: {text}",
        )

    requests = [
        ("req-rfi", "RFI: Confirm rebar lap length at column line C-7 against Spec 03 30 00 §2.4.",
         "rfi", "complete",
         "Classified structural; suggested assignee: structural EOR. Draft response prepared for review.",
         "rfi"),
        ("req-schedule", "Pull the two-week lookahead for Ridgeline DC-2 and flag critical-path slips.",
         "schedule", "complete",
         "Lookahead generated. 1 critical-path risk: MV switchgear delivery (A1450) — 4-day float remaining.",
         "schedules"),
        ("req-estimate", "Estimate cost impact of the fiber duct bank reroute (north run rock excavation).",
         "estimate", "processing", None, "estimates"),
    ]
    for slug, message, intent, status_, response, module in requests:
        await upsert(
            session, RequestRecord, slug,
            user_id=owner_id, message=f"demo-seed: {message}",
            intent=intent, status=status_, response=response,
            output_module=module,
            created_at=now - timedelta(hours=3),
            updated_at=now - timedelta(hours=2),
        )


async def seed_supply_chain(session, today: date) -> None:
    vendors = [
        ("vendor-cummins", dict(
            name="Cummins Power Systems", category="generator",
            contact_name="J. Ortiz", contact_email="jortiz@cummins.example.com",
            prequalified=True, performance_score=8.7,
            notes="demo-seed: framework agreement in place.")),
        ("vendor-vertiv", dict(
            name="Vertiv", category="cooling",
            contact_name="S. Lin", contact_email="slin@vertiv.example.com",
            prequalified=True, performance_score=9.1,
            notes="demo-seed: CRAH + UPS supplier.")),
        ("vendor-abb", dict(
            name="ABB Electrification", category="switchgear",
            contact_name="M. Keller", contact_email="mkeller@abb.example.com",
            prequalified=False, performance_score=7.8,
            notes="demo-seed: prequalification audit scheduled.")),
    ]
    for slug, fields in vendors:
        await upsert(session, Vendor, slug, **fields)

    ridgeline = demo_id("project-ridgeline")
    equipment = [
        ("eq-generators", dict(
            name="3.0 MW Diesel Generators (×8)", category="generator",
            manufacturer="Cummins", model_number="C3000D6E", quantity=8,
            unit_cost_usd=1_450_000.0, lead_time_weeks=28,
            order_date=today - timedelta(days=190),
            expected_delivery=today + timedelta(days=8),
            status="ordered", vendor_id=demo_id("vendor-cummins"),
            notes="demo-seed: on schedule; witness test complete.")),
        ("eq-switchgear", dict(
            name="MV Switchgear Lineup — 34.5kV", category="switchgear",
            manufacturer="ABB", model_number="UniGear ZS1", quantity=2,
            unit_cost_usd=2_100_000.0, lead_time_weeks=38,
            order_date=today - timedelta(days=240),
            expected_delivery=today + timedelta(days=4),
            status="in_transit", vendor_id=demo_id("vendor-abb"),
            notes="demo-seed: AT RISK — arriving inside the 7-day risk window; rigging crew on standby.")),
        ("eq-crah", dict(
            name="CRAH Units (×24)", category="cooling",
            manufacturer="Vertiv", model_number="Liebert CWA", quantity=24,
            unit_cost_usd=85_000.0, lead_time_weeks=16,
            order_date=today - timedelta(days=160),
            expected_delivery=today - timedelta(days=32),
            actual_delivery=today - timedelta(days=30),
            status="received", vendor_id=demo_id("vendor-vertiv"),
            notes="demo-seed: received; staged in warehouse B.")),
        ("eq-ups", dict(
            name="UPS Modules 1.2 MW (×6)", category="ups",
            manufacturer="Vertiv", model_number="Trinergy Cube", quantity=6,
            unit_cost_usd=620_000.0, lead_time_weeks=22,
            status="not_ordered", vendor_id=demo_id("vendor-vertiv"),
            notes="demo-seed: PO pending final single-line revision.")),
    ]
    for slug, fields in equipment:
        await upsert(session, Equipment, slug, project_id=ridgeline, **fields)


async def seed_customers(session, now: datetime) -> None:
    tickets = [
        # Helios — healthy: closed tickets only
        ("tik-helios-1", "acct-helios", "P3", "closed",
         "Cross-connect request — hall A cage 12",
         "Add two cross-connects to carrier meet-me room.",
         "Completed by smart hands; customer confirmed.", now - timedelta(days=21), now - timedelta(days=20)),
        ("tik-helios-2", "acct-helios", "P4", "closed",
         "Badge access update for new SRE team",
         "Add 4 badges to access list for hall A.",
         "Badges issued.", now - timedelta(days=10), now - timedelta(days=9)),
        # Voltaic — at risk: open P1 (aged) + in-progress P2 + one resolved
        ("tik-voltaic-p1", "acct-voltaic", "P1", "open",
         "Packet loss on redundant fabric uplink",
         "Intermittent 2-3% packet loss on uplink B from cage V-4 since maintenance window.",
         None, now - timedelta(days=2), None),
        ("tik-voltaic-p2", "acct-voltaic", "P2", "in_progress",
         "Hot spot in cage V-4 rack 07",
         "Inlet temps trending 4°F above SLA band during training runs.",
         None, now - timedelta(days=1), None),
        ("tik-voltaic-res", "acct-voltaic", "P3", "resolved",
         "Billing portal access for new finance contact",
         "Grant portal access to new AP contact.",
         "Access granted.", now - timedelta(days=12), now - timedelta(days=11)),
        # Northbeam — new customer: one open P3
        ("tik-northbeam-1", "acct-northbeam", "P3", "open",
         "Onboarding: remote hands SOP walkthrough",
         "Schedule SOP walkthrough for Northbeam ops team.",
         None, now - timedelta(hours=20), None),
    ]
    for slug, acct, sev, status_, title, desc, resolution, created, resolved in tickets:
        await upsert(
            session, SupportTicket, slug,
            account_id=demo_id(acct), severity=sev, status=status_,
            title=title, description=f"demo-seed: {desc}",
            resolution_notes=resolution,
            created_at=created, resolved_at=resolved,
        )

    notes = [
        ("note-helios", "acct-helios", "QBR complete — expansion interest for 2027 capacity; reference customer."),
        ("note-voltaic", "acct-voltaic", "Escalation path opened with network vendor on uplink B; exec update daily until P1 clears."),
        ("note-northbeam", "acct-northbeam", "Onboarding week 1 — welcome pack sent, portal accounts provisioned."),
    ]
    for slug, acct, text in notes:
        await upsert(
            session, AccountNote, slug,
            account_id=demo_id(acct), text=f"demo-seed: {text}", created_by="demo-seed",
        )


async def seed_finance(session, today: date) -> None:
    helios = demo_id("acct-helios")
    voltaic = demo_id("acct-voltaic")
    helios_deal = demo_id("deal-helios-won")

    invoices = [
        # Helios — $1.5M/month (== $18M ARR / 12). 3 paid, 1 current, 2 aging.
        ("inv-helios-1", helios, helios_deal, "INV-2026-0141", 1_500_000.0, "paid",
         today - timedelta(days=128), today - timedelta(days=98), today - timedelta(days=101)),
        ("inv-helios-2", helios, helios_deal, "INV-2026-0162", 1_500_000.0, "paid",
         today - timedelta(days=98), today - timedelta(days=68), today - timedelta(days=70)),
        ("inv-helios-3", helios, helios_deal, "INV-2026-0183", 1_500_000.0, "paid",
         today - timedelta(days=68), today - timedelta(days=38), today - timedelta(days=40)),
        ("inv-helios-4", helios, helios_deal, "INV-2026-0204", 1_500_000.0, "overdue",
         today - timedelta(days=102), today - timedelta(days=72), None),   # 61-90 bucket
        ("inv-helios-5", helios, helios_deal, "INV-2026-0225", 1_500_000.0, "overdue",
         today - timedelta(days=68), today - timedelta(days=38), None),    # 31-60 bucket
        ("inv-helios-6", helios, helios_deal, "INV-2026-0246", 1_500_000.0, "sent",
         today - timedelta(days=15), today + timedelta(days=15), None),    # current
        # Voltaic — smaller legacy colo contract
        ("inv-voltaic-1", voltaic, None, "INV-2026-0210", 420_000.0, "paid",
         today - timedelta(days=85), today - timedelta(days=55), today - timedelta(days=57)),
        ("inv-voltaic-2", voltaic, None, "INV-2026-0231", 420_000.0, "overdue",
         today - timedelta(days=55), today - timedelta(days=25), None),    # 1-30 bucket
    ]
    for slug, acct, deal, number, amount, status_, issued, due, paid in invoices:
        await upsert(
            session, Invoice, slug,
            account_id=acct, deal_id=deal, invoice_number=number,
            amount_usd=amount, status=status_,
            issue_date=issued, due_date=due, paid_date=paid,
            notes="demo-seed",
        )

    ridgeline = demo_id("project-ridgeline")
    # Budget lines sum to the Ridgeline project budget ($120M). Equipment
    # committed == supply-chain equipment capex (8×1.45M + 2×2.1M + 24×85k + 6×620k).
    budget_lines = [
        ("bl-land", "land", "Land acquisition + site control", 8_000_000.0, 8_000_000.0, 8_000_000.0),
        ("bl-construction", "construction", "GC contract — shell, MEP, fit-out", 62_000_000.0, 48_500_000.0, 31_200_000.0),
        ("bl-equipment", "equipment", "Long-lead electrical + mechanical equipment", 34_000_000.0, 21_560_000.0, 6_240_000.0),
        ("bl-opex", "opex", "Owner soft costs, commissioning, insurance", 6_000_000.0, 2_100_000.0, 1_800_000.0),
        ("bl-contingency", "contingency", "Owner contingency", 10_000_000.0, 0.0, 0.0),
    ]
    for slug, category, desc, budget, committed, actual in budget_lines:
        await upsert(
            session, BudgetLine, slug,
            project_id=ridgeline, category=category,
            description=f"demo-seed: {desc}",
            budget_usd=budget, committed_usd=committed, actual_usd=actual,
            period=today.strftime("%Y-%m"),
            notes="demo-seed",
        )


async def seed_compliance(session, today: date) -> None:
    campus_id = demo_id("campus-bluecreek")

    obligations = [
        ("obl-capacity-report", dict(
            title="Blue Creek — quarterly capacity report to Helios",
            obligation_type="reporting", due_date=today - timedelta(days=10),
            recurrence="quarterly", status="overdue",
            description="Contractual quarterly capacity + uptime report (MSA §7.2).")),
        ("obl-gc-cert", dict(
            title="Ridgeline DC-2 — GC payment milestone certification",
            obligation_type="payment", due_date=today + timedelta(days=12),
            recurrence="monthly", status="open",
            description="Certify pay app #14 before GC invoice release.")),
        ("obl-insurance-cert", dict(
            title="Blue Creek — annual insurance certificate delivery",
            obligation_type="notice", due_date=today - timedelta(days=40),
            recurrence="annual", status="complete",
            description="Deliver renewed COI to anchor customer per lease.")),
    ]
    for slug, fields in obligations:
        await upsert(session, ContractObligation, slug, notes="demo-seed", **fields)

    regulatory = [
        ("reg-epa-spcc", dict(
            title="EPA SPCC plan update — Blue Creek diesel storage",
            framework="epa", jurisdiction="US-OH", due_date=today + timedelta(days=30),
            recurrence="annual", status="in_progress", responsible_party="Facilities — EHS",
            description="Update SPCC plan for the added belly-tank capacity.")),
        ("reg-oh-air", dict(
            title="Ohio EPA air permit renewal — Ridgeline DC-2 gensets",
            framework="state", jurisdiction="US-OH", due_date=today + timedelta(days=75),
            recurrence="annual", status="open", responsible_party="Owner's engineer",
            description="PTI/PTO renewal covering 8 × 3.0 MW emergency generators.")),
        ("reg-nerc", dict(
            title="NERC registration applicability review",
            framework="nerc", jurisdiction="US", due_date=today - timedelta(days=60),
            recurrence="annual", status="complete", responsible_party="Compliance counsel",
            description="Annual review — load-only, registration not required.")),
    ]
    for slug, fields in regulatory:
        await upsert(session, RegulatoryItem, slug, notes="demo-seed", **fields)

    insurance = [
        ("ins-property", dict(
            policy_name="Blue Creek Campus — Property & Business Interruption",
            policy_type="property", carrier="FM Global", policy_number="FMG-88231-DEMO",
            coverage_amount_usd=250_000_000.0, premium_annual_usd=1_150_000.0,
            effective_date=today - timedelta(days=344), expiry_date=today + timedelta(days=21),
            status="active")),
        ("ins-builders", dict(
            policy_name="Ridgeline DC-2 — Builder's Risk",
            policy_type="builders_risk", carrier="Zurich", policy_number="ZUR-45102-DEMO",
            coverage_amount_usd=130_000_000.0, premium_annual_usd=780_000.0,
            effective_date=today - timedelta(days=165), expiry_date=today + timedelta(days=200),
            status="active")),
    ]
    for slug, fields in insurance:
        await upsert(session, InsurancePolicy, slug, notes="demo-seed", **fields)

    checklist, _ = await upsert(
        session, ComplianceChecklist, "chk-soc2",
        name="SOC 2 Type II — Blue Creek Campus",
        framework="soc2", campus_id=campus_id, status="active",
    )
    controls = [
        ("chk-soc2-cc11", "CC1.1", "Control environment — org structure & oversight", True),
        ("chk-soc2-cc61", "CC6.1", "Logical access — provisioning & least privilege", True),
        ("chk-soc2-cc62", "CC6.2", "Physical access — badge + biometric at data halls", True),
        ("chk-soc2-cc71", "CC7.1", "Monitoring — infrastructure telemetry & alerting", True),
        ("chk-soc2-cc72", "CC7.2", "Incident response — documented runbooks & drills", True),
        ("chk-soc2-cc81", "CC8.1", "Change management — approvals for infra changes", False),
        ("chk-soc2-a11", "A1.1", "Availability — capacity planning evidence", False),
        ("chk-soc2-a12", "A1.2", "Availability — environmental protections & recovery", False),
    ]
    now = _utcnow()
    for slug, control, title, checked in controls:
        await upsert(
            session, ComplianceChecklistItem, slug,
            checklist_id=checklist.id, control_id=control,
            title=title, description=f"demo-seed control: {control}",
            checked=checked, checked_at=(now - timedelta(days=5)) if checked else None,
            notes="demo-seed",
        )


DEMO_APPROVALS = [
    ("appr-daily-brief", dict(
        agent_id="daily-brief", workflow="brief.morning.compile",
        lane=Lane.AUTO.value, priority=Priority.NORMAL.value,
        target_system=TargetSystem.EMAIL.value,
        api_call="POST /email/send",
        agent_confidence=0.97,
        agent_reasoning="Morning brief compiled from overnight telemetry, queue, and schedule deltas.",
        payload={"brief_date": "auto", "sections": ["incidents", "schedule", "procurement"],
                 "recipients": ["charles@quill.local"]},
        source_artifacts=[{"kind": "report", "ref": "BRIEF-RDG-DAILY"}],
        citations=[{"source_type": "telemetry", "source_id": "bluecreek-ops", "excerpt": "PUE 1.21, 1 open P2"}])),
    ("appr-rfi-231", dict(
        agent_id="rfi-triage", workflow="rfi.classify",
        lane=Lane.SINGLE.value, priority=Priority.NORMAL.value,
        target_system=TargetSystem.PROCORE.value,
        api_call="POST /procore/projects/{pid}/rfis/{id}/classify",
        agent_confidence=0.88,
        agent_reasoning="RFI-RDG-0231 references Spec 03 30 00 §2.4; matches structural reinforcement category.",
        payload={"rfi_id": "RFI-RDG-0231", "project": "Ridgeline DC-2",
                 "category": "structural", "spec_section": "03 30 00",
                 "suggested_assignee": "structural-EOR"},
        source_artifacts=[{"kind": "rfi", "ref": "RFI-RDG-0231",
                           "excerpt": "Confirm rebar lap length at column line C-7."}],
        citations=[{"source_type": "spec_section", "source_id": "03 30 00 §2.4",
                    "excerpt": "Min lap 48d_b for #8 and smaller"}])),
    ("appr-sub-118", dict(
        agent_id="submittal-spec-validator", workflow="submittal.review.first-pass",
        lane=Lane.SINGLE.value, priority=Priority.HIGH.value,
        target_system=TargetSystem.PROCORE.value,
        agent_confidence=0.76,
        agent_reasoning="Arc-flash study SUB-RDG-0118 uses 2018 IEEE 1584 tables; spec requires 2022 edition.",
        payload={"submittal_id": "SUB-RDG-0118", "project": "Ridgeline DC-2",
                 "finding": "revise_and_resubmit",
                 "delta": {"ieee_1584_edition": "2018 vs 2022"}},
        source_artifacts=[{"kind": "submittal", "ref": "SUB-RDG-0118"}],
        citations=[{"source_type": "spec_section", "source_id": "26 05 73 §1.6",
                    "excerpt": "Arc-flash study per IEEE 1584-2022"}])),
    ("appr-switchgear-slip", dict(
        agent_id="procurement-watch", workflow="po.long_lead.alert",
        lane=Lane.DUAL.value, priority=Priority.CRITICAL_PATH.value,
        target_system=TargetSystem.NONE.value,
        agent_confidence=0.93,
        agent_reasoning="MV switchgear (Ridgeline DC-2) delivery window inside 7 days with rigging not yet confirmed; CP activity A1450 has 4 days float.",
        payload={"po_id": "PO-2026-0388", "vendor": "ABB",
                 "equipment": "MV Switchgear Lineup — 34.5kV",
                 "project": "Ridgeline DC-2", "float_days": 4,
                 "cp_activities": ["A1450", "A1455"],
                 "recommendation": "Authorize weekend rigging crew + escrow release on delivery"},
        source_artifacts=[{"kind": "schedule_activity", "ref": "A1450"}],
        citations=[{"source_type": "po_record", "source_id": "PO-2026-0388",
                    "excerpt": "ETA T+4 days; site rigging unconfirmed"}])),
]


async def seed_approvals(session) -> int:
    created = 0
    for slug, spec in DEMO_APPROVALS:
        pk = demo_id(slug)
        existing = await session.get(ApprovalItem, pk)
        if existing is not None:
            continue  # keep any human decisions made on demo items
        lane = spec["lane"]
        priority = spec["priority"]
        item = ApprovalItem(
            id=pk,
            agent_id=spec["agent_id"],
            agent_version="0.1.0",
            workflow=spec["workflow"],
            lane=lane,
            priority=priority,
            target_system=spec["target_system"],
            api_call=spec.get("api_call"),
            payload=spec["payload"],
            source_artifacts=spec["source_artifacts"],
            citations=spec["citations"],
            agent_confidence=spec["agent_confidence"],
            agent_reasoning=spec["agent_reasoning"],
            required_approvers=required_approvers_for_lane(lane),
            sla_due_at=compute_sla_due(lane, priority),
        )
        session.add(item)
        await session.flush()
        entry = await record_event(
            session,
            event_type="approval.created",
            actor="demo-seed",
            approval_item_id=item.id,
            payload={"agent_id": item.agent_id, "workflow": item.workflow, "lane": lane},
        )
        item.audit_hash = entry.hash
        item.prev_audit_hash = entry.prev_hash
        created += 1
    return created


# ---------------------------------------------------------------------------
# DataSite sites (optional — separate DB via DATASITE_DATABASE_URL)
# ---------------------------------------------------------------------------

def _site_record(slug: str, *, address: str, city: str, state: str, zip_: str,
                 county: str, status: str, workload: str, mw: float,
                 acres: float, asking: float, score: float | None,
                 verdict: str | None, decision: str | None,
                 summary: str | None, created: datetime) -> dict:
    site_id = DEMO_SITE_UUIDS[slug]
    weights = {"power": 0.30, "fiber": 0.15, "permitting": 0.15, "environmental": 0.15,
               "land": 0.10, "water": 0.05, "market": 0.05, "financial": 0.03,
               "title": 0.01, "geotechnical": 0.01}
    per_criterion = {"site-jackson": {
        "power": 88, "fiber": 82, "permitting": 84, "environmental": 78, "land": 85,
        "water": 74, "market": 80, "financial": 76, "title": 90, "geotechnical": 72,
    }}.get(slug, {})
    scores: dict = {}
    for criterion, weight in weights.items():
        raw = per_criterion.get(criterion)
        scores[criterion] = {
            "score": raw,
            "weight": weight,
            "weighted_score": round(raw * weight, 2) if raw is not None else None,
            "evidence": f"demo-seed evidence for {criterion}" if raw is not None else None,
            "kill_switch_triggered": False,
        }
    scores["total_weighted"] = score
    scores["kill_switches_triggered"] = []
    return {
        "site_id": site_id,
        "demo_seed": True,
        "created_at": created.isoformat(),
        "updated_at": created.isoformat(),
        "status": status,
        "lead_source": "broker",
        "property": {
            "address": address, "city": city, "state": state, "zip": zip_,
            "county": county, "apn": None, "lat": None, "lng": None,
            "acres": acres, "asking_price": asking,
            "price_per_acre": round(asking / acres, 2) if asking and acres else None,
            "zoning_current": "Heavy industrial" if status == "decided" else None,
            "owner_name": None, "owner_type": None,
        },
        "target_workload": workload,
        "target_mw": mw,
        "research": ({"power": "345kV corridor 1.2 mi; AEP queue position confirmed (demo-seed)"}
                     if status != "intake" else {}),
        "documents": [],
        "scores": scores,
        "recommendation": {
            "verdict": verdict, "summary": summary,
            "strengths": (["Utility-scale power proximity", "Fiber long-haul routes", "Favorable county permitting"]
                          if verdict else []),
            "risks": (["Karst pockets flagged in desktop geotech"] if verdict else []),
            "conditions": [], "estimated_timeline_months": 22 if verdict else None,
            "next_steps": [], "generated_at": created.isoformat() if verdict else None,
            "generated_by": "demo-seed" if verdict else None,
        },
        "decision": {
            "final_verdict": decision,
            "decided_by": "demo-seed" if decision else None,
            "decided_at": created.isoformat() if decision else None,
            "notes": "Advanced to project Ridgeline DC-2" if decision == "advance" else None,
        },
    }


def _datasite_engine():
    url = os.environ.get("DATASITE_DATABASE_URL", "").strip()
    if not url:
        return None
    from sqlalchemy import create_engine

    if "asyncpg" in url:
        url = url.replace("postgresql+asyncpg", "postgresql")
    return create_engine(url, pool_pre_ping=True)


def seed_datasite_sites(now: datetime) -> str:
    """Upsert 2 demo sites into the DataSite DB (skipped without env)."""
    engine = _datasite_engine()
    if engine is None:
        return "skipped (DATASITE_DATABASE_URL not set)"

    from sqlalchemy import MetaData, Table

    meta = MetaData()
    sites = Table("sites", meta, autoload_with=engine)
    json_native = "JSON" in type(sites.c.record_json.type).__name__.upper()

    records = [
        dict(
            site_id=DEMO_SITE_UUIDS["site-jackson"],
            status="decided",
            address="8821 State Route 32", city="Jackson", state="OH", zip="45640",
            county="Jackson County", target_workload="hyperscale", target_mw=60.0,
            lead_source="broker", total_weighted_score=82.4,
            recommendation_verdict="strong_recommend", final_decision="advance",
            record_json=_site_record(
                "site-jackson", address="8821 State Route 32", city="Jackson",
                state="OH", zip_="45640", county="Jackson County",
                status="decided", workload="hyperscale", mw=60.0,
                acres=212.0, asking=9_500_000.0, score=82.4,
                verdict="strong_recommend", decision="advance",
                summary="Strong power + fiber fundamentals; advanced to Ridgeline DC-2.",
                created=now - timedelta(days=140)),
            created_at=now - timedelta(days=140), updated_at=now,
        ),
        dict(
            site_id=DEMO_SITE_UUIDS["site-berkeley"],
            status="researching",
            address="1210 Meadowfield Industrial Rd", city="Moncks Corner", state="SC",
            zip="29461", county="Berkeley County", target_workload="ai_hpc",
            target_mw=45.0, lead_source="broker", total_weighted_score=None,
            recommendation_verdict=None, final_decision=None,
            record_json=_site_record(
                "site-berkeley", address="1210 Meadowfield Industrial Rd",
                city="Moncks Corner", state="SC", zip_="29461",
                county="Berkeley County", status="researching", workload="ai_hpc",
                mw=45.0, acres=165.0, asking=11_200_000.0, score=None,
                verdict=None, decision=None, summary=None,
                created=now - timedelta(days=18)),
            created_at=now - timedelta(days=18), updated_at=now,
        ),
    ]

    with engine.begin() as conn:
        for rec in records:
            if not json_native:
                rec = {**rec, "record_json": json.dumps(rec["record_json"])}
            conn.execute(sites.delete().where(sites.c.site_id == rec["site_id"]))
            conn.execute(sites.insert().values(**rec))
    engine.dispose()
    return f"seeded {len(records)} demo sites"


def wipe_datasite_sites() -> str:
    engine = _datasite_engine()
    if engine is None:
        return "skipped (DATASITE_DATABASE_URL not set)"
    from sqlalchemy import MetaData, Table

    meta = MetaData()
    sites = Table("sites", meta, autoload_with=engine)
    with engine.begin() as conn:
        removed = 0
        for site_uuid in DEMO_SITE_UUIDS.values():
            result = conn.execute(sites.delete().where(sites.c.site_id == site_uuid))
            removed += result.rowcount or 0
    engine.dispose()
    return f"removed {removed} demo sites"


# ---------------------------------------------------------------------------
# Wipe / counts
# ---------------------------------------------------------------------------

async def demo_counts(session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for model in DEMO_TABLES:
        result = await session.execute(
            select(func.count()).select_from(model).where(model.id.like(f"{DEMO_PREFIX}%"))
        )
        counts[model.__tablename__] = int(result.scalar_one())
    return counts


async def wipe(session) -> dict[str, int]:
    removed: dict[str, int] = {}
    for model in DEMO_TABLES:
        result = await session.execute(
            delete(model).where(model.id.like(f"{DEMO_PREFIX}%"))
        )
        removed[model.__tablename__] = result.rowcount or 0
    # Audit chain is append-only: record the wipe, never delete entries.
    await record_event(
        session,
        event_type="demo.seed.wiped",
        actor="demo-seed",
        approval_item_id=None,
        payload={"removed": {k: v for k, v in removed.items() if v}},
    )
    await session.commit()
    return removed


# ---------------------------------------------------------------------------
# Expected dashboard numbers — used by scripts/verify_demo_dashboards.py
# ---------------------------------------------------------------------------

def expected_numbers() -> dict:
    """Dashboard numbers attributable to the demo dataset alone.

    On a fresh local DB these are the absolute dashboard values; on prod they
    are deltas on top of pre-existing rows.
    """
    return {
        "finance": {
            "total_arr_usd": 18_000_000.0,
            "total_pipeline_value_usd": 23_500_000.0,          # 12.5M + 6.8M + 4.2M
            "total_capex_committed_usd": 21_560_000.0,          # all demo equipment
            "capex_equipment_usd": 17_840_000.0,                # ordered/in_transit/received
            "total_project_budget_usd": 215_000_000.0,          # 120M + 95M
            "total_project_forecast_usd": 218_700_000.0,        # 124.5M + 94.2M
            "total_outstanding_invoices_usd": 4_920_000.0,      # 3×1.5M + 0.42M
            "overdue_invoices_count": 3,
        },
        "pipeline": {
            "total_active_deals": 3,
            "total_active_mw": 29.0,
            "total_active_value_usd": 23_500_000.0,
            "won_value_usd": 18_000_000.0,
            "win_rate_pct": 50.0,
        },
        "operations": {
            "campuses": 1,
            "mw_capacity": 48.0,
            "mw_live": 36.0,
            "pue_current": 1.21,
            "open_p1_p2_incidents": 1,
            "incidents_total": 3,
        },
        "customers": {
            "total_customers": 3,
            "open_tickets": 3,
            "has_critical_tickets": True,
        },
        "supply_chain": {
            "total_equipment_items": 4,
            "total_equipment_value_usd": 21_560_000.0,
            "at_risk_count": 1,
            "vendor_count": 3,
            "approved_vendor_count": 2,
        },
        "compliance": {
            "overdue_obligations": 1,
            "expiring_insurance_30d": 1,
            "open_regulatory_items": 2,
            "checklists_complete_pct": 62.5,                    # 5 of 8 controls
        },
        "intelligence": {
            "mw_under_site_control": 48.0,
            "mw_under_construction": 0.0,
            "mw_live": 36.0,
            "total_arr_usd": 18_000_000.0,
            "pipeline_value_usd": 23_500_000.0,
            "active_incidents_p1_p2": 1,
            "avg_pue": 1.21,
            "open_customer_tickets": 3,
            "at_risk_equipment_count": 1,
            "active_projects": 1,                               # Ridgeline (Blue Creek complete)
            "active_customers": 3,
        },
        "approvals": {"pending_demo_items": len(DEMO_APPROVALS)},
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_seed() -> None:
    now = _utcnow()
    today = now.date()
    async with db_module.SessionLocal() as session:
        owner_id = await resolve_owner_id(session)

        # Safety: never mutate the real Adams Fork rows — assert we don't hold them.
        assert ADAMS_FORK_PROJECT_ID not in {demo_id(s) for s in ("project-ridgeline", "project-bluecreek")}

        await seed_projects(session, owner_id, now, today)
        await seed_operations(session, now)
        await seed_pipeline(session, today)
        await seed_customers(session, now)
        await seed_supply_chain(session, today)
        await seed_finance(session, today)
        await seed_compliance(session, today)
        created_approvals = await seed_approvals(session)
        await session.commit()

        counts = await demo_counts(session)

    print(f"approvals created this run: {created_approvals}")
    print("demo row counts by table:")
    for table, count in counts.items():
        if count:
            print(f"  {table}: {count}")
    print("datasite:", seed_datasite_sites(now))
    print("expected demo dashboard numbers:")
    print(json.dumps(expected_numbers(), indent=2))
    print("seed_demo complete:", _utcnow().isoformat())


async def run_wipe() -> None:
    async with db_module.SessionLocal() as session:
        before = await demo_counts(session)
        removed = await wipe(session)
        after = await demo_counts(session)
    print("demo rows removed:")
    for table, count in removed.items():
        if count:
            print(f"  {table}: {count}")
    leftover = {t: c for t, c in after.items() if c}
    if leftover:
        print("WARNING — demo rows remain:", leftover)
    else:
        print("all demo rows removed (audit-chain entries preserved by design)")
    print("before:", sum(before.values()), "after:", sum(after.values()))
    print("datasite:", wipe_datasite_sites())


async def run_counts() -> None:
    async with db_module.SessionLocal() as session:
        counts = await demo_counts(session)
    print(json.dumps(counts, indent=2))
    print("total demo rows:", sum(counts.values()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wipe", action="store_true", help="remove all demo rows (and demo DataSite sites)")
    parser.add_argument("--counts", action="store_true", help="print demo row counts and exit")
    args = parser.parse_args()

    if args.wipe:
        asyncio.run(run_wipe())
    elif args.counts:
        asyncio.run(run_counts())
    else:
        asyncio.run(run_seed())


if __name__ == "__main__":
    main()
