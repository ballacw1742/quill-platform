"""API-side workflow-assignment governance (ADK_AGENTS_DESIGN.md §4).

Owner-only decide + never-auto-execute are the core safety invariants. These
test the pure governance predicates that gate the decide/create paths, so
they run without a DB fixture. The predicates are the same functions the
service's decide_approval/create_approval call, so a regression in the guard
fails here.
"""

from __future__ import annotations

from app.enums import (
    OWNER_ONLY_WORKFLOWS,
    WORKFLOW_ASSIGNMENT_WORKFLOW,
    Lane,
    UserRole,
)
from app.services import approvals as approvals_svc


def test_workflow_assignment_is_owner_only():
    assert WORKFLOW_ASSIGNMENT_WORKFLOW in OWNER_ONLY_WORKFLOWS
    assert approvals_svc.is_owner_only_workflow(WORKFLOW_ASSIGNMENT_WORKFLOW)


def test_non_owner_cannot_decide_owner_only_workflow():
    for role in ("partner", "observer", "agent", "viewer", "admin"):
        assert not approvals_svc.owner_only_decide_allowed(
            WORKFLOW_ASSIGNMENT_WORKFLOW, role
        ), f"role {role} must NOT be able to decide a workflow_assignment"


def test_owner_can_decide_owner_only_workflow():
    assert approvals_svc.owner_only_decide_allowed(
        WORKFLOW_ASSIGNMENT_WORKFLOW, UserRole.OWNER.value
    )
    # Case-insensitive.
    assert approvals_svc.owner_only_decide_allowed(
        WORKFLOW_ASSIGNMENT_WORKFLOW, "OWNER"
    )


def test_normal_workflow_defers_to_normal_authority():
    # Non-owner-only workflows are not gated by this predicate (the normal
    # required_approvers check applies instead).
    assert approvals_svc.owner_only_decide_allowed("agentcloud.project_update", "partner")
    assert approvals_svc.owner_only_decide_allowed("site_advance.create_project", "partner")


def test_required_approvers_owner_only_when_forced():
    # required_approvers override wins (create_approval forces ['owner'] for
    # owner-only workflows).
    assert approvals_svc.required_approvers_for_lane(
        Lane.DUAL.value, ["owner"]
    ) == ["owner"]
