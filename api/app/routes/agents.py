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
        "display_name": "RFI Triage",
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

    # Workflow fleet — register any missing slugs (parity with all envs).
    for slug in AGENT_FLEET:
        existing = await session.get(AgentRegistration, slug)
        if existing is not None:
            continue
        tier, default_lane = FLEET_CONFIG.get(slug, (TrustTier.TIER_0, Lane.SINGLE))
        session.add(
            AgentRegistration(
                agent_id=slug,
                version="0.1.0",
                trust_tier=tier.value,
                default_lane=default_lane.value,
                monthly_token_budget=1_000_000,
                enabled=True,
            )
        )

    await session.commit()
    log.info(
        "agents.seed completed (%d adk + %d fleet agents)",
        len(SEED_AGENTS),
        len(AGENT_FLEET),
    )
