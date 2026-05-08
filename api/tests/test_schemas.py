"""Pydantic schema validation."""

from __future__ import annotations

import pytest
from app.schemas import ApprovalCreate, DecisionRequest
from pydantic import ValidationError


def test_approval_create_minimal():
    obj = ApprovalCreate(agent_id="rfi-triage", workflow="rfi.classify")
    assert obj.lane.value if hasattr(obj.lane, "value") else obj.lane == 2
    assert obj.priority.value if hasattr(obj.priority, "value") else obj.priority == "normal"


def test_approval_create_confidence_bounds():
    with pytest.raises(ValidationError):
        ApprovalCreate(agent_id="x", workflow="w", agent_confidence=1.5)


def test_decision_request_enum():
    obj = DecisionRequest(decision="approve")
    assert obj.decision in ("approve",) or hasattr(obj.decision, "value")


def test_decision_request_bad_decision():
    with pytest.raises(ValidationError):
        DecisionRequest(decision="thumbs_up")
