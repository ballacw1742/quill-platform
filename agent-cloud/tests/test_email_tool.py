"""Tests for quill_email_send approval-gated tool (§9 Wave 2, MIGRATION.md §3.3)."""

from __future__ import annotations

import json
import pytest

import app.approvals as approvals_mod
from app import events as events_mod
from app.logging_setup import agent_id_var, session_id_var, tenant_id_var
from app.tools import REGISTRY, run_tool
from app.tools.quill_writes import EMAIL_WRITE_TOOL_NAMES, EMAIL_WRITE_TOOLS, quill_email_send

TENANT = "smoke-email-tool"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_queue(monkeypatch):
    """Capture the POST /v1/approvals call instead of hitting the network."""
    calls: list[dict] = []

    async def _fake_post(payload):
        calls.append(payload)
        return {"id": f"appr-email-{len(calls)}", "status": "pending"}

    monkeypatch.setattr(approvals_mod, "_post_approval", _fake_post)
    return calls


@pytest.fixture
def ctx():
    """Set tool contextvars the way stream_turn does before tools run."""
    t1 = tenant_id_var.set(TENANT)
    t2 = agent_id_var.set("quill")
    t3 = session_id_var.set(None)
    yield
    tenant_id_var.reset(t1)
    agent_id_var.reset(t2)
    session_id_var.reset(t3)


# ---------------------------------------------------------------------------
# Registry / catalog
# ---------------------------------------------------------------------------

def test_email_tool_in_registry():
    assert "quill_email_send" in REGISTRY


def test_email_write_tool_names():
    assert "quill_email_send" in EMAIL_WRITE_TOOL_NAMES


def test_email_write_tools_list():
    names = [t.name for t in EMAIL_WRITE_TOOLS]
    assert "quill_email_send" in names


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "args,expected_error_fragment",
    [
        # Missing required fields
        ({"subject": "Hi", "body": "Hello"}, "to"),
        ({"to": "a@b.com", "body": "Hello"}, "subject"),
        ({"to": "a@b.com", "subject": "Hi"}, "body"),
        # Invalid email
        ({"to": "not-an-email", "subject": "Hi", "body": "Hello"}, "email"),
        ({"to": "missing-at-sign.com", "subject": "Hi", "body": "Hello"}, "email"),
        # subject too long
        ({"to": "a@b.com", "subject": "x" * 201, "body": "Hello"}, "200"),
        # body too long
        ({"to": "a@b.com", "subject": "Hi", "body": "x" * 10_001}, "10000"),
        # invalid cc element
        ({"to": "a@b.com", "subject": "Hi", "body": "Hello", "cc": ["bad-email"]}, "email"),
        # cc not a list
        ({"to": "a@b.com", "subject": "Hi", "body": "Hello", "cc": "also@b.com"}, "list"),
    ],
)
def test_validate_args_email_rejects(args, expected_error_fragment):
    with pytest.raises(approvals_mod.ProposalValidationError, match=expected_error_fragment):
        approvals_mod.validate_args("email_send", args)


def test_validate_args_email_minimal_valid():
    result = approvals_mod.validate_args("email_send", {
        "to": "recipient@example.com",
        "subject": "Test Subject",
        "body": "Hello world",
    })
    assert result["to"] == "recipient@example.com"
    assert result["subject"] == "Test Subject"
    assert result["body"] == "Hello world"
    assert "cc" not in result


def test_validate_args_email_with_cc():
    result = approvals_mod.validate_args("email_send", {
        "to": "a@example.com",
        "subject": "Sub",
        "body": "Body",
        "cc": ["b@example.com", "c@example.com"],
    })
    assert result["cc"] == ["b@example.com", "c@example.com"]


def test_validate_args_email_empty_cc_omitted():
    result = approvals_mod.validate_args("email_send", {
        "to": "a@example.com",
        "subject": "Sub",
        "body": "Body",
        "cc": [],
    })
    assert "cc" not in result


def test_validate_args_email_rejects_unknown_key():
    with pytest.raises(approvals_mod.ProposalValidationError, match="unknown"):
        approvals_mod.validate_args("email_send", {
            "to": "a@b.com",
            "subject": "Hi",
            "body": "Hello",
            "bcc": "sneaky@b.com",
        })


# ---------------------------------------------------------------------------
# Tool handler (with fake queue)
# ---------------------------------------------------------------------------

async def test_email_tool_queues_proposal(ctx, fake_queue):
    """Happy path: valid args → proposal created → pending_approval returned."""
    args = {
        "to": "manager@example.com",
        "subject": "Q2 update",
        "body": "Please see the attached Q2 summary.",
    }
    result_json = await quill_email_send.handler(args)
    result = json.loads(result_json)

    assert result.get("status") == "pending_approval"
    assert result.get("proposal_id")

    # One POST to approvals API
    assert len(fake_queue) == 1
    posted = fake_queue[0]
    assert posted["workflow"] == "agentcloud.email_send"
    assert posted["lane"] == 2
    pa = posted["payload"]["proposed_action"]
    assert pa["action"] == "email_send"
    assert pa["args"]["to"] == "manager@example.com"


async def test_email_tool_returns_error_on_invalid_email(ctx):
    """Invalid email address → tool returns error JSON, nothing queued."""
    args = {
        "to": "not-valid",
        "subject": "Oops",
        "body": "Body",
    }
    result_json = await quill_email_send.handler(args)
    result = json.loads(result_json)
    assert "error" in result
    assert "email" in result["error"].lower() or "invalid" in result["error"].lower()


async def test_email_tool_emits_event(ctx, fake_queue):
    """Successful proposal emits email.send_queued event."""
    args = {
        "to": "receiver@example.com",
        "subject": "Hello",
        "body": "World",
    }
    await quill_email_send.handler(args)

    bus = events_mod.get_bus()
    # Give the ensure_future a chance to run
    import asyncio
    await asyncio.sleep(0)

    email_events = [
        e for e in bus.published
        if e.get("type") == "email.send_queued"
    ]
    assert len(email_events) >= 1
    payload = email_events[0]["payload"]
    assert payload["to"] == "receiver@example.com"
    assert payload["subject"] == "Hello"


async def test_email_tool_no_tenant_context():
    """Without tenant context, tool returns an error (not a crash)."""
    # No ctx fixture → tenant_id_var is unset
    args = {"to": "a@b.com", "subject": "Hi", "body": "Body"}
    result_json = await quill_email_send.handler(args)
    result = json.loads(result_json)
    assert "error" in result


async def test_email_tool_accessible_via_run_tool(ctx, fake_queue):
    """Tool can be called via the registry run_tool path."""
    args = {"to": "test@example.com", "subject": "Registry test", "body": "Hi"}
    result_json = await run_tool("quill_email_send", args, ["quill_email_send"])
    result = json.loads(result_json)
    assert result.get("status") == "pending_approval"


async def test_email_tool_with_cc(ctx, fake_queue):
    """CC list is validated and passed through to the proposal."""
    args = {
        "to": "a@example.com",
        "subject": "Multi-recipient",
        "body": "See below.",
        "cc": ["b@example.com", "c@example.com"],
    }
    result_json = await quill_email_send.handler(args)
    result = json.loads(result_json)
    assert result.get("status") == "pending_approval"

    pa = fake_queue[0]["payload"]["proposed_action"]
    assert pa["args"]["cc"] == ["b@example.com", "c@example.com"]


async def test_email_tool_reasoning_forwarded(ctx, fake_queue):
    """reasoning is extracted and passed as agent_reasoning to the approval."""
    args = {
        "to": "a@example.com",
        "subject": "Sub",
        "body": "Body",
        "reasoning": "This was requested by Charles.",
    }
    await quill_email_send.handler(args)
    assert fake_queue[0].get("agent_reasoning") == "This was requested by Charles."


def test_email_send_queued_in_event_types():
    """email.send_queued must be a registered event type."""
    from app.events import EVENT_TYPES
    assert "email.send_queued" in EVENT_TYPES
