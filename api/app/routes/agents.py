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

from app.models import AgentRegistration

log = logging.getLogger("quill.agents")

# ---------------------------------------------------------------------------
# Seed data — 9 agents (5 PMO + 4 DataSite)
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
]


async def seed_agents(session: AsyncSession) -> None:
    """Upsert the 9 seed agents into agent_registrations.

    Called from main.py lifespan. Safe to call multiple times (idempotent).
    Only sets display/registry fields — does not overwrite trust_tier,
    default_lane, or monthly_token_budget set by admins.
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

    await session.commit()
    log.info("agents.seed completed (%d agents)", len(SEED_AGENTS))
