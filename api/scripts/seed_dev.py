"""Seed dev DB: Charles user, agent registrations, sample pending approvals."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app import db as db_module
from app.enums import AGENT_FLEET, Lane, Priority, TargetSystem, TrustTier, UserRole
from app.models import AgentRegistration, ApprovalItem, User
from app.security import hash_password
from app.services.approvals import compute_sla_due, required_approvers_for_lane
from app.services.audit import record_event
from sqlalchemy import select

CHARLES_EMAIL = "charles@quill.local"
CHARLES_PASSWORD = "quill-dev-password"  # dev only

FLEET_CONFIG = {
    "coordinator": (TrustTier.TIER_2, Lane.AUTO),
    "rfi-triage": (TrustTier.TIER_1, Lane.SINGLE),
    "rfi-drafter": (TrustTier.TIER_0, Lane.SINGLE),
    "submittal-triage": (TrustTier.TIER_1, Lane.SINGLE),
    "submittal-spec-validator": (TrustTier.TIER_0, Lane.SINGLE),
    "daily-brief": (TrustTier.TIER_2, Lane.AUTO),
    "procurement-watch": (TrustTier.TIER_1, Lane.SINGLE),
    # PM agents — Phase C. Four artifact producers default to single-signer
    # (Charles approves before publish to the Documents tab); the runtime
    # bumps to dual-signer (Lane.DUAL) for owner-facing distribution per
    # PM_AGENTS_SPEC. knowledge-manager is auto-archive (Lane.AUTO) per the
    # PM_AGENTS_SPEC "auto-archive to Documents for searchability" rule;
    # it carries TIER_1 (single-signer / spot-check) as its prompt-side
    # trust tier so the runtime forces a tier-0 review on confidence < 0.70
    # or controversial-decision flags.
    "status-update-author": (TrustTier.TIER_1, Lane.SINGLE),
    "project-coordinator": (TrustTier.TIER_1, Lane.SINGLE),
    "project-manager": (TrustTier.TIER_1, Lane.SINGLE),
    "comms-drafter": (TrustTier.TIER_1, Lane.SINGLE),
    "knowledge-manager": (TrustTier.TIER_1, Lane.AUTO),
}

SAMPLE_APPROVALS = [
    {
        "agent_id": "rfi-triage",
        "workflow": "rfi.classify",
        "lane": Lane.SINGLE.value,
        "priority": Priority.NORMAL.value,
        "target_system": TargetSystem.PROCORE.value,
        "api_call": "POST /procore/projects/{pid}/rfis/{id}/classify",
        "agent_confidence": 0.86,
        "agent_reasoning": "RFI references Spec 03 30 00 §2.4; matches reinforcement category.",
        "payload": {
            "rfi_id": "RFI-DCC-0142",
            "category": "structural",
            "spec_section": "03 30 00",
            "suggested_assignee": "structural-EOR",
        },
        "source_artifacts": [
            {"kind": "rfi", "ref": "RFI-DCC-0142", "excerpt": "Confirm rebar lap length at column C-7."}
        ],
        "citations": [
            {"source_type": "spec_section", "source_id": "03 30 00 §2.4", "excerpt": "Min lap 48d_b"}
        ],
    },
    {
        "agent_id": "submittal-spec-validator",
        "workflow": "submittal.review.first-pass",
        "lane": Lane.SINGLE.value,
        "priority": Priority.HIGH.value,
        "target_system": TargetSystem.PROCORE.value,
        "agent_confidence": 0.74,
        "agent_reasoning": "Concrete mix design 4500 psi vs spec 5000 psi — flag for review.",
        "payload": {
            "submittal_id": "SUB-DCC-0087",
            "finding": "non_compliant",
            "delta": {"compressive_strength": "4500 vs 5000"},
        },
        "source_artifacts": [{"kind": "submittal", "ref": "SUB-DCC-0087"}],
        "citations": [
            {"source_type": "spec_section", "source_id": "03 30 00 §3.1", "excerpt": "f'c = 5000 psi"}
        ],
    },
    {
        "agent_id": "procurement-watch",
        "workflow": "po.long_lead.alert",
        "lane": Lane.DUAL.value,
        "priority": Priority.CRITICAL_PATH.value,
        "target_system": TargetSystem.NONE.value,
        "agent_confidence": 0.92,
        "agent_reasoning": "MV switchgear lead time slipped 6 weeks; impacts CP activity A1450.",
        "payload": {
            "po_id": "PO-2026-0411",
            "vendor": "ABB",
            "slip_weeks": 6,
            "cp_activities": ["A1450", "A1455"],
        },
        "source_artifacts": [{"kind": "schedule_activity", "ref": "A1450"}],
        "citations": [
            {"source_type": "po_record", "source_id": "PO-2026-0411", "excerpt": "ETA shifted Q1→Q2"}
        ],
    },
]


async def main() -> None:
    async with db_module.SessionLocal() as session:
        # Charles user
        existing = await session.execute(select(User).where(User.email == CHARLES_EMAIL))
        user = existing.scalars().first()
        if user is None:
            user = User(
                email=CHARLES_EMAIL,
                display_name="Charles Mitchell",
                role=UserRole.OWNER.value,
                password_hash=hash_password(CHARLES_PASSWORD),
            )
            session.add(user)
            await session.flush()
            print(f"created user: {CHARLES_EMAIL} (id={user.id})")
        else:
            print(f"user exists: {CHARLES_EMAIL}")

        # Agent fleet
        for slug in AGENT_FLEET:
            existing = await session.get(AgentRegistration, slug)
            if existing:
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
        await session.flush()
        print(f"registered {len(AGENT_FLEET)} agents")

        # Sample approvals — only seed if queue empty.
        existing = (await session.execute(select(ApprovalItem).limit(1))).scalars().first()
        if existing is None:
            for spec in SAMPLE_APPROVALS:
                lane = spec["lane"]
                priority = spec["priority"]
                item = ApprovalItem(
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
                    actor="seed",
                    approval_item_id=item.id,
                    payload={"agent_id": item.agent_id, "workflow": item.workflow, "lane": lane},
                )
                item.audit_hash = entry.hash
                item.prev_audit_hash = entry.prev_hash
            await session.commit()
            print(f"seeded {len(SAMPLE_APPROVALS)} sample approvals")
        else:
            print("approvals already present, skipping sample seed")

        await session.commit()
    print("seed complete:", datetime.now(UTC).isoformat())


if __name__ == "__main__":
    asyncio.run(main())
