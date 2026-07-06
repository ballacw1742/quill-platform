"""Agent Registry — Sprint DC.4

This module provides the seed_agents() function called from main.py lifespan
to upsert the 9 ADK agents into agent_registrations on startup.

Routes for GET /v1/agents, GET /v1/agents/{id}, and PATCH /v1/agents/{id}/toggle
are handled in admin.py (which owns the /v1 prefix).
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import AGENT_FLEET, Lane, TrustTier
from app.models import AgentRegistration

log = logging.getLogger("quill.agents")

# ---------------------------------------------------------------------------
# Seed data — 15 agents (5 PMO + 4 DataSite + 6 specialist data agents)
# ---------------------------------------------------------------------------
ADK_ENDPOINT = "https://quill-adk-agents-894031978246.us-central1.run.app"

SEED_AGENTS: list[dict] = [
    {
        "agent_id": "quill_coordinator",
        "display_name": "Quill Coordinator",
        "description": "Routes inbound PMO requests to the right specialist agent. Entry point for all general and unclassified requests.",
        "role_summary": "Orchestrator",
        "handled_intents": ["general", "estimate"],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
    {
        "agent_id": "quill_rfi_triage",
        "display_name": "RFI Triage Agent",
        "description": "Processes Requests for Information — triages, routes to the right party, and drafts responses.",
        "role_summary": "RFI Management",
        "handled_intents": ["rfi"],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
    {
        "agent_id": "quill_change_order",
        "display_name": "Change Order Agent",
        "description": "Analyzes change orders for cost and schedule impact, flags risks, drafts responses.",
        "role_summary": "Change Order Processing",
        "handled_intents": ["contract"],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
    {
        "agent_id": "quill_schedule_monitor",
        "display_name": "Schedule Monitor",
        "description": "Analyzes project schedules, identifies critical path issues, and flags milestone risks.",
        "role_summary": "Schedule Analysis",
        "handled_intents": ["schedule"],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
    {
        "agent_id": "quill_status_report",
        "display_name": "Status Report Agent",
        "description": "Generates owner-facing project status reports and executive summaries.",
        "role_summary": "Reporting",
        "handled_intents": [],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
    {
        "agent_id": "datasite_site_evaluator",
        "display_name": "Site Evaluator",
        "description": "Submits new data center site candidates for DataSite Intelligence Go/No-Go scoring.",
        "role_summary": "Site Intake & Evaluation",
        "handled_intents": ["site_evaluation"],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
    {
        "agent_id": "datasite_site_researcher",
        "display_name": "Site Researcher",
        "description": "Researches utility availability, fiber infrastructure, permitting, and market conditions for site evaluations.",
        "role_summary": "Site Research",
        "handled_intents": ["site_research"],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
    {
        "agent_id": "datasite_site_scorer",
        "display_name": "Site Scorer",
        "description": "Explains scoring results across 10 evaluation criteria and compares site candidates.",
        "role_summary": "Scoring & Analysis",
        "handled_intents": ["site_scoring"],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
    {
        "agent_id": "datasite_site_status",
        "display_name": "Site Status",
        "description": "Provides real-time pipeline visibility — tracks sites from intake through final verdict.",
        "role_summary": "Pipeline Status",
        "handled_intents": ["site_status"],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
    # -----------------------------------------------------------------------
    # Sprint 5.2 — specialist data agents (6 new)
    # -----------------------------------------------------------------------
    {
        "agent_id": "quill_facility_ops",
        "display_name": "Facility Operations Agent",
        "description": "Answers questions about campus status, incidents, PUE, uptime, and power metrics. Can query live campus data and surface active P1/P2 incidents.",
        "role_summary": "Facility Operations",
        "handled_intents": ["campus", "incident", "uptime", "pue", "facility", "power", "outage"],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
    {
        "agent_id": "quill_sales",
        "display_name": "Sales & Pipeline Agent",
        "description": "Answers questions about deals, accounts, pipeline value, win rates, and activity history. Can summarize deal status and flag stalled deals.",
        "role_summary": "Sales & Pipeline",
        "handled_intents": ["deal", "pipeline", "account", "prospect", "won", "lost", "sales", "revenue", "crm"],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
    {
        "agent_id": "quill_customer_success",
        "display_name": "Customer Success Agent",
        "description": "Answers questions about customer health scores, support tickets, and account notes. Can surface at-risk customers and open P1/P2 tickets.",
        "role_summary": "Customer Success",
        "handled_intents": ["customer", "ticket", "support", "health", "churn", "at-risk", "satisfaction", "nps"],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
    {
        "agent_id": "quill_finance",
        "display_name": "Finance Agent",
        "description": "Answers questions about ARR, invoices, cash position, capex, and budget vs actuals. Surfaces overdue invoices and budget variances.",
        "role_summary": "Finance",
        "handled_intents": ["finance", "invoice", "revenue", "arr", "budget", "cash", "capex", "payment", "overdue"],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
    {
        "agent_id": "quill_intelligence",
        "display_name": "Executive Intelligence Agent",
        "description": "Provides cross-module executive summaries: business health, risk flags, and KPI rollups across Operations, Sales, Finance, and Customer Success.",
        "role_summary": "Executive Intelligence",
        "handled_intents": ["intelligence", "executive", "summary", "kpi", "dashboard", "briefing", "status", "overview"],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
    {
        "agent_id": "quill_compliance",
        "display_name": "Compliance Agent",
        "description": "Answers questions about compliance checklists, upcoming regulatory deadlines, and contract obligations. Flags overdue or at-risk items.",
        "role_summary": "Compliance",
        "handled_intents": ["compliance", "regulatory", "deadline", "obligation", "checklist", "audit", "permit", "legal"],
        "framework": "adk",
        "endpoint_url": ADK_ENDPOINT,
    },
]


# Trust tier / lane defaults for the workflow fleet (AGENT_FLEET slugs).
# Anything not listed defaults to (TIER_0, SINGLE). Insert-only — admin
# changes to these fields are never overwritten by the startup seed.
FLEET_CONFIG: dict[str, tuple[TrustTier, Lane]] = {
    "coordinator": (TrustTier.TIER_2, Lane.AUTO),
    "rfi-triage": (TrustTier.TIER_1, Lane.SINGLE),
    "rfi-drafter": (TrustTier.TIER_0, Lane.SINGLE),
    "submittal-triage": (TrustTier.TIER_1, Lane.SINGLE),
    "submittal-spec-validator": (TrustTier.TIER_0, Lane.SINGLE),
    "daily-brief": (TrustTier.TIER_2, Lane.AUTO),
    "procurement-watch": (TrustTier.TIER_1, Lane.SINGLE),
}


# Display metadata for the workflow fleet — upserted on every startup seed
# (same treatment as the ADK agents) so the registry UI shows proper names,
# descriptions, and role summaries. Trust tier / lane / budget stay insert-only.
FLEET_METADATA: dict[str, dict[str, str]] = {
    "coordinator": {
        "display_name": "Fleet Coordinator",
        "description": "Orchestrates the workflow fleet — routes incoming work to the right specialist agent, sequences multi-agent workflows, and tracks task completion across the fleet.",
        "role_summary": "Fleet Orchestration",
    },
    "rfi-triage": {
        "display_name": "RFI Triage",
        "description": "Classifies incoming RFIs by discipline and urgency, checks for duplicates against open RFIs, and routes each to the right reviewer with a suggested priority.",
        "role_summary": "RFI Intake & Routing",
    },
    "rfi-drafter": {
        "display_name": "RFI Response Drafter",
        "description": "Drafts RFI responses from spec sections, drawings, and prior correspondence, with citations to source documents for reviewer sign-off.",
        "role_summary": "RFI Response Drafting",
    },
    "submittal-triage": {
        "display_name": "Submittal Triage",
        "description": "Logs incoming submittals, matches them to spec sections and the submittal register, and routes them to the responsible reviewer with due-date tracking.",
        "role_summary": "Submittal Intake & Routing",
    },
    "submittal-spec-validator": {
        "display_name": "Submittal Spec Validator",
        "description": "Checks submittal contents against the governing spec section — flags missing data, non-compliant products, and deviations before human review.",
        "role_summary": "Spec Compliance Checking",
    },
    "schedule-reader": {
        "display_name": "Schedule Reader",
        "description": "Parses project schedules to answer questions about activities, dates, float, and logic ties, and surfaces upcoming milestones and slipped activities.",
        "role_summary": "Schedule Analysis",
    },
    "critical-path-watch": {
        "display_name": "Critical Path Watch",
        "description": "Monitors schedule updates for critical-path changes — flags new drivers, float erosion, and milestone risk before they become delays.",
        "role_summary": "Critical Path Monitoring",
    },
    "dfr-synthesizer": {
        "display_name": "Daily Field Report Synthesizer",
        "description": "Compiles daily field reports from crew notes, photos, weather, and delivery logs into a structured DFR ready for superintendent review.",
        "role_summary": "Field Reporting",
    },
    "safety-aggregator": {
        "display_name": "Safety Aggregator",
        "description": "Aggregates safety observations, incidents, and toolbox-talk records across sites — tracks trends and flags recurring hazards for the safety team.",
        "role_summary": "Safety Tracking",
    },
    "progress-capture": {
        "display_name": "Progress Capture",
        "description": "Records installed quantities and percent-complete against the schedule of values, keeping progress data current for billing and earned-value tracking.",
        "role_summary": "Progress Tracking",
    },
    "co-estimator": {
        "display_name": "Change Order Estimator",
        "description": "Prices change orders — builds cost breakdowns from unit rates, quotes, and historical data, and drafts the CO package for estimator review.",
        "role_summary": "Change Order Pricing",
    },
    "daily-brief": {
        "display_name": "Daily Brief",
        "description": "Produces the morning project brief — overnight developments, today's priorities, open approvals, and items at risk, delivered before the workday starts.",
        "role_summary": "Daily Briefing",
    },
    "ccb-prep": {
        "display_name": "Change Control Board Prep",
        "description": "Prepares Change Control Board packets — assembles pending change orders with pricing, schedule impact, and recommendations into a review-ready agenda.",
        "role_summary": "CCB Preparation",
    },
    "owner-reporting": {
        "display_name": "Owner Reporting",
        "description": "Assembles recurring owner reports — progress summaries, budget status, schedule health, and open issues — formatted for external distribution.",
        "role_summary": "Owner Communications",
    },
    "procurement-watch": {
        "display_name": "Procurement Watch",
        "description": "Tracks procurement and long-lead items against required-on-site dates — flags at-risk deliveries and expediting needs before they impact the schedule.",
        "role_summary": "Procurement Tracking",
    },
}


async def seed_agents(session: AsyncSession) -> None:
    """Seed the agent registry: ADK agents (upsert) + workflow fleet (insert-only).

    Called from main.py lifespan. Safe to call multiple times (idempotent).
    For ADK agents, only display/registry fields are updated — trust_tier,
    default_lane, and monthly_token_budget set by admins are never touched.
    Workflow-fleet agents are inserted if missing and never modified after.
    """
    for data in SEED_AGENTS:
        agent = await session.get(AgentRegistration, data["agent_id"])
        if agent is None:
            agent = AgentRegistration(
                agent_id=data["agent_id"],
                version="1.0.0",
            )
            session.add(agent)

        # Update registry fields (upsert style — only registry metadata)
        agent.display_name = data["display_name"]
        agent.description = data["description"]
        agent.role_summary = data["role_summary"]
        agent.handled_intents = json.dumps(data["handled_intents"])
        agent.framework = data["framework"]
        agent.endpoint_url = data["endpoint_url"]

    # Workflow fleet — insert missing slugs (parity with all envs), then
    # upsert display metadata (names/descriptions) same as the ADK agents.
    # Trust tier, lane, and budget remain insert-only (admin-owned).
    for slug in AGENT_FLEET:
        agent = await session.get(AgentRegistration, slug)
        if agent is None:
            tier, default_lane = FLEET_CONFIG.get(slug, (TrustTier.TIER_0, Lane.SINGLE))
            agent = AgentRegistration(
                agent_id=slug,
                version="0.1.0",
                trust_tier=tier.value,
                default_lane=default_lane.value,
                monthly_token_budget=1_000_000,
                enabled=True,
            )
            session.add(agent)

        meta = FLEET_METADATA.get(slug)
        if meta is not None:
            agent.display_name = meta["display_name"]
            agent.description = meta["description"]
            agent.role_summary = meta["role_summary"]
            agent.framework = "internal"

    await session.commit()
    log.info(
        "agents.seed completed (%d adk + %d fleet agents)",
        len(SEED_AGENTS),
        len(AGENT_FLEET),
    )
