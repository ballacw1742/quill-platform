"""Shared enums for models + schemas. Single source of truth."""

from __future__ import annotations

from enum import Enum


class Lane(int, Enum):
    """Three approval lanes per the Quill spec.

    1 — auto-execute (Tier 2 trust)
    2 — single approver (Charles)
    3 — dual approval (Charles + partner)
    """

    AUTO = 1
    SINGLE = 2
    DUAL = 3


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL_PATH = "critical_path"


class TargetSystem(str, Enum):
    PROCORE = "procore"
    P6 = "p6"
    ACC = "acc"
    DRIVE = "drive"
    EMAIL = "email"
    # ADK_AGENTS_DESIGN.md §4: workflow-assignment approvals target the
    # workflow-definition data (stage→agent mapping), not an external system.
    WORKFLOW = "workflow"
    NONE = "none"


# ADK_AGENTS_DESIGN.md §4 — agent-cloud approval workflows that require an
# OWNER decision and can NEVER auto-execute regardless of agent trust tier.
# A workflow_assignment changes a LIVE workflow (which agent runs at a stage),
# so it is always human-owner-gated (extends Phase 1's money/contract/
# irreversible rule to workflow/code changes).
WORKFLOW_ASSIGNMENT_WORKFLOW = "agentcloud.workflow_assignment"
OWNER_ONLY_WORKFLOWS = frozenset({WORKFLOW_ASSIGNMENT_WORKFLOW})

# Phase D — Deliverable HITL gate: approval workflow constant.
# A deliverable-acceptance decision is a normal owner single-sig (Lane SINGLE).
# NEVER auto-execute (Lane AUTO is expressly prohibited for deliverable gates).
DELIVERABLE_ACCEPT_WORKFLOW = "deliverable.accept"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"
    EXECUTED = "executed"
    EXECUTION_FAILED = "execution_failed"
    SUSPENDED = "suspended"  # litigation hold
    EXPIRED = "expired"  # SLA breach hard cap (future)


class ExecutionResult(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    DRY_RUN = "dry_run"


class Decision(str, Enum):
    APPROVE = "approve"
    EDIT_THEN_APPROVE = "edit_then_approve"
    REJECT = "reject"
    ESCALATE = "escalate"


class AuthMethod(str, Enum):
    DEV_TOKEN = "dev_token"
    PASSWORD = "password"
    PASSKEY = "passkey"
    WEBAUTHN = "webauthn"


class TrustTier(str, Enum):
    TIER_0 = "tier-0-mandatory"
    TIER_1 = "tier-1-spotcheck"
    TIER_2 = "tier-2-auto"


class UserRole(str, Enum):
    OWNER = "owner"  # Charles
    PARTNER = "partner"  # dual-approval partner
    OBSERVER = "observer"
    AGENT = "agent"


# Slugs for the agent fleet — kept aligned with approval_queue_item.schema.json.
AGENT_FLEET = (
    "coordinator",
    "rfi-triage",
    "rfi-drafter",
    "submittal-triage",
    "submittal-spec-validator",
    "schedule-reader",
    "critical-path-watch",
    "dfr-synthesizer",
    "safety-aggregator",
    "progress-capture",
    "co-estimator",
    "daily-brief",
    "ccb-prep",
    "owner-reporting",
    "procurement-watch",
)
