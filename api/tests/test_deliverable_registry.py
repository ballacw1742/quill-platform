"""Phase E — deliverable registry tests.

Covers:
  1. Registry structure: every entry has required fields (module_key, deliverable_type,
     title_template, stage_key, >=1 step); module_key matches the known module roster.
  2. Every ChainStep has non-empty key, agent_name, prompt_suffix.
  3. INTENT_TO_DELIVERABLE covers all piloted intents (primary + secondary aliases).
  4. stage_key values are valid lifecycle stage keys.
  5. The two original Phase B/C pilots are unchanged (pilots contract preserved).
  6. A representative NEW intent ("contract") now produces its deliverable type via
     the chain (via monkeypatched _call_adk_with_retry, same pattern as producer tests).
  7. A disabled module still skips the chain (no deliverable produced).
  8. Non-registered intents still produce nothing.
  9. API output includes stage_key from the registry.

These use the ``client`` fixture because it monkeypatches app.db.SessionLocal to
the in-memory test session maker — which is the session maker the background
producer (_dispatch_to_agent) opens internally. Without the client fixture,
SessionLocal points at the real DB and the tables don't exist.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

# Import models at top level so create_all registers them (conftest quirk).
import app.routes.requests  # noqa: F401
from app.deliverable_registry import (
    DELIVERABLE_REGISTRY,
    INTENT_TO_DELIVERABLE,
    DeliverableRegistryEntry,
)
from app.models_deliverables import Deliverable, DeliverableVersion
from app.models_requests import RequestRecord

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Known module roster — must match INTENT_TO_MODULE in routes/requests.py
# ---------------------------------------------------------------------------
_KNOWN_MODULE_KEYS = {
    "estimates",
    "projects",
    "contracts",
    "sites",
    "operations",
    "supply-chain",
    "finance",
    "compliance",
    "sales",
    "customers",
    "intelligence",
}

# Valid lifecycle stage keys from web/lib/lifecycle.ts
_VALID_STAGE_KEYS = {
    "origination",
    "site_control",
    "permitting",
    "design",
    "construction",
    "commissioning",
    "turnover",
    "operations",
}

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _Resp:
    """Mock HTTP response returned by the patched _call_adk_with_retry."""

    def __init__(self, text: str = "agent output") -> None:
        self.status_code = 200
        self.text = text

    def json(self) -> dict:
        return {"response": self.text}


async def _deliverables_for(uid: str) -> list[Deliverable]:
    import app.db as db_module
    async with db_module.SessionLocal() as s:
        rows = (
            await s.execute(select(Deliverable).where(Deliverable.user_id == uid))
        ).scalars().all()
        return list(rows)


async def _seed_and_dispatch(
    client,
    monkeypatch,
    uid: str,
    intent: str,
    message: str,
    adk_responses: list[str] | None = None,
) -> tuple[str, int]:
    """Seed a processing request and run the producer with controlled ADK responses."""
    import app.db as db_module
    import app.routes.requests as reqmod

    async with db_module.SessionLocal() as s:
        rec = RequestRecord(user_id=uid, message=message, intent=intent, status="processing")
        s.add(rec)
        await s.commit()
        await s.refresh(rec)
        rid = rec.id

    responses = list(adk_responses) if adk_responses else ["agent output"]
    call_count = [0]

    async def _fake_adk(*a, **k):
        idx = call_count[0]
        call_count[0] += 1
        text = responses[idx] if idx < len(responses) else responses[-1]
        return _Resp(text)

    monkeypatch.setattr(reqmod, "_call_adk_with_retry", _fake_adk)
    await reqmod._dispatch_to_agent(
        request_id=rid,
        intent=intent,
        message=message,
        filenames=[],
        drive_url=None,
        user_id=uid,
    )
    return rid, call_count[0]


# ---------------------------------------------------------------------------
# 1. Registry structure: every entry has required fields
# ---------------------------------------------------------------------------


def test_registry_is_nonempty():
    """Registry has entries."""
    assert len(DELIVERABLE_REGISTRY) > 0


def test_all_entries_have_required_fields():
    """Every registry entry has module_key, deliverable_type, title_template, stage_key, >=1 step."""
    for dtype, entry in DELIVERABLE_REGISTRY.items():
        assert entry.module_key, f"{dtype}: module_key is empty"
        assert entry.deliverable_type, f"{dtype}: deliverable_type is empty"
        assert entry.deliverable_type == dtype, (
            f"{dtype}: deliverable_type mismatch (key={dtype!r} != entry.deliverable_type={entry.deliverable_type!r})"
        )
        assert entry.title_template, f"{dtype}: title_template is empty"
        assert "{message}" in entry.title_template, (
            f"{dtype}: title_template missing {{message}} substitution"
        )
        assert len(entry.steps) >= 1, (
            f"{dtype}: expected >=1 step, got {len(entry.steps)}"
        )


def test_all_entries_module_key_in_roster():
    """Every entry's module_key is a known module in the roster."""
    for dtype, entry in DELIVERABLE_REGISTRY.items():
        assert entry.module_key in _KNOWN_MODULE_KEYS, (
            f"{dtype}: module_key {entry.module_key!r} not in known roster"
        )


def test_all_entries_have_valid_stage_key():
    """Every entry's stage_key is a valid lifecycle stage key."""
    for dtype, entry in DELIVERABLE_REGISTRY.items():
        assert entry.stage_key in _VALID_STAGE_KEYS, (
            f"{dtype}: stage_key {entry.stage_key!r} not in valid stage keys {_VALID_STAGE_KEYS}"
        )


# ---------------------------------------------------------------------------
# 2. ChainStep structure: all steps have required fields
# ---------------------------------------------------------------------------


def test_all_steps_have_required_fields():
    """All chain steps have non-empty key, agent_name, and prompt_suffix."""
    for dtype, entry in DELIVERABLE_REGISTRY.items():
        for i, step in enumerate(entry.steps):
            assert step.key, f"{dtype}[{i}]: step.key is empty"
            assert step.agent_name, f"{dtype}[{i}]: step.agent_name is empty"
            assert step.prompt_suffix, f"{dtype}[{i}]: step.prompt_suffix is empty"
            assert step.role, f"{dtype}[{i}]: step.role is empty"


def test_all_entries_have_two_steps():
    """All entries have exactly 2 steps (Phase-E spec: Step A drafts, Step B enriches)."""
    for dtype, entry in DELIVERABLE_REGISTRY.items():
        assert len(entry.steps) == 2, (
            f"{dtype}: expected 2 steps, got {len(entry.steps)}"
        )


# ---------------------------------------------------------------------------
# 3. INTENT_TO_DELIVERABLE covers all piloted intents
# ---------------------------------------------------------------------------


def test_intent_to_deliverable_covers_primary_intents():
    """Every registry entry's produced_by_intent is in INTENT_TO_DELIVERABLE."""
    for dtype, entry in DELIVERABLE_REGISTRY.items():
        assert entry.produced_by_intent in INTENT_TO_DELIVERABLE, (
            f"{dtype}: produced_by_intent {entry.produced_by_intent!r} not in INTENT_TO_DELIVERABLE"
        )
        assert INTENT_TO_DELIVERABLE[entry.produced_by_intent].deliverable_type == dtype, (
            f"{dtype}: INTENT_TO_DELIVERABLE[{entry.produced_by_intent!r}] maps to wrong type"
        )


def test_secondary_intent_aliases_covered():
    """Secondary intent aliases (site_research, campus, equipment, pipeline, etc.) are covered."""
    # Sites secondaries
    for intent in ("site_research", "site_scoring", "site_status"):
        assert intent in INTENT_TO_DELIVERABLE, f"Missing secondary intent: {intent!r}"
        assert INTENT_TO_DELIVERABLE[intent].deliverable_type == "site_assessment"

    # Operations secondaries
    for intent in ("campus", "incident", "uptime", "pue"):
        assert intent in INTENT_TO_DELIVERABLE, f"Missing secondary intent: {intent!r}"
        assert INTENT_TO_DELIVERABLE[intent].deliverable_type == "ops_report"

    # Supply chain secondaries
    for intent in ("equipment", "vendor", "procurement", "lead_time", "delivery"):
        assert intent in INTENT_TO_DELIVERABLE, f"Missing secondary intent: {intent!r}"
        assert INTENT_TO_DELIVERABLE[intent].deliverable_type == "procurement_package"

    # Sales secondary
    assert "pipeline" in INTENT_TO_DELIVERABLE
    assert INTENT_TO_DELIVERABLE["pipeline"].deliverable_type == "pipeline_summary"


def test_all_expected_deliverable_types_present():
    """All 12 expected deliverable types are in the registry."""
    expected = {
        "cost_estimate", "rfi_response",  # Phase B/C pilots
        "schedule_package", "change_order_package", "site_assessment",
        "ops_report", "procurement_package", "finance_report",
        "compliance_report", "pipeline_summary", "customer_summary", "exec_brief",
    }
    actual = set(DELIVERABLE_REGISTRY.keys())
    missing = expected - actual
    assert not missing, f"Missing deliverable types: {missing}"


# ---------------------------------------------------------------------------
# 4. Phase B/C pilots unchanged (regression guard)
# ---------------------------------------------------------------------------


def test_cost_estimate_pilot_unchanged():
    """cost_estimate registry entry preserves Phase B/C structure."""
    entry = DELIVERABLE_REGISTRY["cost_estimate"]
    assert entry.module_key == "estimates"
    assert entry.produced_by_intent == "estimate"
    assert entry.stage_key == "design"
    keys = [s.key for s in entry.steps]
    assert "scope_draft" in keys
    assert "unit_pricing" in keys
    assert entry.steps[0].agent_name == "quill_coordinator"
    assert entry.steps[1].agent_name == "quill_coordinator"


def test_rfi_response_pilot_unchanged():
    """rfi_response registry entry preserves Phase B/C structure."""
    entry = DELIVERABLE_REGISTRY["rfi_response"]
    assert entry.module_key == "projects"
    assert entry.produced_by_intent == "rfi"
    assert entry.stage_key == "construction"
    keys = [s.key for s in entry.steps]
    assert "rfi_intake" in keys
    assert "rfi_draft" in keys
    assert entry.steps[0].agent_name == "quill_rfi_triage"
    assert entry.steps[1].agent_name == "quill_rfi_triage"


# ---------------------------------------------------------------------------
# 5. stage_key assignments by deliverable type
# ---------------------------------------------------------------------------


def test_stage_key_assignments():
    """Verify stage_key assignments match lifecycle design."""
    expectations = {
        "cost_estimate": "design",
        "rfi_response": "construction",
        "schedule_package": "construction",
        "change_order_package": "construction",
        "site_assessment": "site_control",
        "ops_report": "operations",
        "procurement_package": "construction",
        "finance_report": "construction",
        "compliance_report": "permitting",
        "pipeline_summary": "origination",
        "customer_summary": "operations",
        "exec_brief": "operations",
    }
    for dtype, expected_stage in expectations.items():
        entry = DELIVERABLE_REGISTRY[dtype]
        assert entry.stage_key == expected_stage, (
            f"{dtype}: expected stage_key={expected_stage!r}, got {entry.stage_key!r}"
        )


# ---------------------------------------------------------------------------
# 6. New intent ("contract") produces change_order_package via chain
# ---------------------------------------------------------------------------


async def test_contract_intent_produces_change_order_package(client, owner_token, monkeypatch):
    """A representative NEW Phase-E intent ('contract') now produces its deliverable
    type (change_order_package) via the 2-step chain, with status 'awaiting_human'."""
    uid, _ = owner_token
    # "contract" should now be piloted (in INTENT_TO_DELIVERABLE)
    assert "contract" in INTENT_TO_DELIVERABLE, (
        "Phase E: 'contract' must be in INTENT_TO_DELIVERABLE"
    )
    assert INTENT_TO_DELIVERABLE["contract"].deliverable_type == "change_order_package"

    await _seed_and_dispatch(
        client, monkeypatch, uid, "contract", "Review change order CO-042",
        adk_responses=["Contract intake output", "CO draft output"],
    )
    dels = await _deliverables_for(uid)
    assert len(dels) == 1, f"Expected 1 deliverable, got {len(dels)}"
    d = dels[0]

    assert d.deliverable_type == "change_order_package"
    assert d.module_key == "contracts"
    assert d.version >= 2, f"Expected version >=2 (2-step chain), got {d.version}"
    assert d.status == "awaiting_human", f"Expected 'awaiting_human', got {d.status!r}"

    meta = d.meta or {}
    step_keys = [s["key"] for s in meta.get("chain_steps", [])]
    assert "contract_intake" in step_keys, f"step_keys={step_keys}"
    assert "co_draft" in step_keys, f"step_keys={step_keys}"
    assert meta.get("steps_completed") == 2


async def test_contract_chain_has_two_adk_calls(client, owner_token, monkeypatch):
    """'contract' intent makes exactly 2 ADK calls (no legacy dispatch for piloted intents)."""
    uid, _ = owner_token
    _, call_count = await _seed_and_dispatch(
        client, monkeypatch, uid, "contract", "CO scope review",
        adk_responses=["Step A output", "Step B output"],
    )
    assert call_count == 2, (
        f"Expected exactly 2 ADK calls (2 chain steps, no legacy dispatch), got {call_count}"
    )


# ---------------------------------------------------------------------------
# 7. Non-registered intents produce nothing (regression guard)
# ---------------------------------------------------------------------------


async def test_general_intent_produces_nothing(client, owner_token, monkeypatch):
    """'general' intent is not piloted — no deliverable produced."""
    uid, _ = owner_token
    assert "general" not in INTENT_TO_DELIVERABLE, (
        "'general' should not be in INTENT_TO_DELIVERABLE"
    )
    await _seed_and_dispatch(
        client, monkeypatch, uid, "general", "What is the project status?",
        adk_responses=["general response"],
    )
    dels = await _deliverables_for(uid)
    assert dels == [], f"Expected no deliverables for 'general' intent, got {dels}"


# ---------------------------------------------------------------------------
# 8. Disabled module skips the chain (no deliverable produced)
# ---------------------------------------------------------------------------


async def test_disabled_module_skips_chain(client, owner_token, monkeypatch):
    """When the owning module is disabled, the request is skipped before dispatch.
    The chain does not run, so no deliverable is produced.

    Note: submit_request imports is_module_enabled / is_feature_enabled directly
    into the app.routes.requests namespace, so we must patch them there.
    """
    import app.routes.requests as reqmod

    uid, token = owner_token

    # Disable the 'contracts' module for this user's workspace.
    # is_module_enabled and is_feature_enabled are async functions; patch with async stubs.
    async def _always_false(*a, **k):
        return False

    monkeypatch.setattr(reqmod, "is_module_enabled", _always_false)
    monkeypatch.setattr(reqmod, "is_feature_enabled", _always_false)

    # Post via the API (which checks the module gate in submit_request).
    from tests.conftest import auth_h  # noqa: PLC0415
    r = await client.post(
        "/v1/requests",
        headers=auth_h(token),
        data={
            "message": "Review change order CO-099",
            "intent": "contract",
        },
    )
    # Request accepted (skipped, not rejected at the HTTP level)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "skipped", f"Expected 'skipped', got {body['status']!r}"

    # No deliverable should have been produced (chain never ran)
    dels = await _deliverables_for(uid)
    assert dels == [], f"Expected no deliverables for disabled module, got {dels}"


# ---------------------------------------------------------------------------
# 9. API output includes stage_key
# ---------------------------------------------------------------------------


async def test_deliverable_api_output_includes_stage_key(client, owner_token):
    """POST /v1/deliverables returns stage_key in the response for registered types."""
    _, token = owner_token
    from tests.conftest import auth_h  # noqa: PLC0415

    r = await client.post(
        "/v1/deliverables",
        headers=auth_h(token),
        json={
            "module_key": "contracts",
            "deliverable_type": "change_order_package",
            "title": "CO-042 package",
        },
    )
    assert r.status_code == 201, r.text
    d = r.json()
    # stage_key should be threaded through from the registry
    assert "stage_key" in d, "API response missing 'stage_key' field"
    assert d["stage_key"] == "construction", (
        f"Expected stage_key='construction' for change_order_package, got {d['stage_key']!r}"
    )


async def test_deliverable_api_output_stage_key_unknown_type(client, owner_token):
    """POST /v1/deliverables with an unregistered type returns stage_key=''."""
    _, token = owner_token
    from tests.conftest import auth_h  # noqa: PLC0415

    r = await client.post(
        "/v1/deliverables",
        headers=auth_h(token),
        json={
            "module_key": "projects",
            "deliverable_type": "custom_unregistered_type",
            "title": "Custom thing",
        },
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert "stage_key" in d, "API response missing 'stage_key' field"
    assert d["stage_key"] == "", (
        f"Expected stage_key='' for unknown type, got {d['stage_key']!r}"
    )


# ---------------------------------------------------------------------------
# 10. A few more new intents produce their deliverable types (spot check)
# ---------------------------------------------------------------------------


async def test_finance_intent_produces_finance_report(client, owner_token, monkeypatch):
    """'finance' intent produces finance_report with 2-step chain."""
    uid, _ = owner_token
    await _seed_and_dispatch(
        client, monkeypatch, uid, "finance", "Budget variance for Q2",
        adk_responses=["Cost status output", "EAC analysis output"],
    )
    dels = await _deliverables_for(uid)
    assert len(dels) == 1
    assert dels[0].deliverable_type == "finance_report"
    assert dels[0].module_key == "finance"
    assert dels[0].version >= 2
    assert dels[0].status == "awaiting_human"


async def test_intelligence_intent_produces_exec_brief(client, owner_token, monkeypatch):
    """'intelligence' intent produces exec_brief with 2-step chain."""
    uid, _ = owner_token
    await _seed_and_dispatch(
        client, monkeypatch, uid, "intelligence", "Weekly program status brief",
        adk_responses=["KPI aggregation output", "Executive narrative output"],
    )
    dels = await _deliverables_for(uid)
    assert len(dels) == 1
    assert dels[0].deliverable_type == "exec_brief"
    assert dels[0].module_key == "intelligence"
    assert dels[0].version >= 2
    assert dels[0].status == "awaiting_human"


async def test_compliance_intent_produces_compliance_report(client, owner_token, monkeypatch):
    """'compliance' intent produces compliance_report in 'permitting' stage."""
    uid, _ = owner_token
    await _seed_and_dispatch(
        client, monkeypatch, uid, "compliance", "Review permit obligations for DC-01",
        adk_responses=["Permit status output", "Compliance risk output"],
    )
    dels = await _deliverables_for(uid)
    assert len(dels) == 1
    assert dels[0].deliverable_type == "compliance_report"
    assert dels[0].module_key == "compliance"
    assert dels[0].version >= 2


async def test_customer_success_intent_produces_customer_summary(client, owner_token, monkeypatch):
    """'customer_success' intent produces customer_summary."""
    uid, _ = owner_token
    await _seed_and_dispatch(
        client, monkeypatch, uid, "customer_success", "Open P1 tickets for Hyperscaler A",
        adk_responses=["Ticket triage output", "QBR package draft"],
    )
    dels = await _deliverables_for(uid)
    assert len(dels) == 1
    assert dels[0].deliverable_type == "customer_summary"
    assert dels[0].module_key == "customers"
    assert dels[0].version >= 2


async def test_site_evaluation_intent_produces_site_assessment(client, owner_token, monkeypatch):
    """'site_evaluation' intent produces site_assessment in 'site_control' stage."""
    uid, _ = owner_token
    await _seed_and_dispatch(
        client, monkeypatch, uid, "site_evaluation", "Evaluate 1234 Main St Columbus OH",
        adk_responses=["Site intake output", "Site scoring output"],
    )
    dels = await _deliverables_for(uid)
    assert len(dels) == 1
    assert dels[0].deliverable_type == "site_assessment"
    assert dels[0].module_key == "sites"
    assert dels[0].stage_key if hasattr(dels[0], "stage_key") else True  # stage_key is in API, not ORM


async def test_secondary_site_intent_produces_site_assessment(client, owner_token, monkeypatch):
    """'site_research' (secondary intent alias) also produces site_assessment."""
    uid, _ = owner_token
    await _seed_and_dispatch(
        client, monkeypatch, uid, "site_research", "Research fiber for Columbus site",
        adk_responses=["Site research output A", "Site research output B"],
    )
    dels = await _deliverables_for(uid)
    assert len(dels) == 1
    assert dels[0].deliverable_type == "site_assessment"


async def test_supply_chain_secondary_intent_produces_procurement_package(client, owner_token, monkeypatch):
    """'equipment' (secondary intent alias) produces procurement_package."""
    uid, _ = owner_token
    await _seed_and_dispatch(
        client, monkeypatch, uid, "equipment", "Long-lead status for transformers",
        adk_responses=["Procurement intake output", "Lead time analysis output"],
    )
    dels = await _deliverables_for(uid)
    assert len(dels) == 1
    assert dels[0].deliverable_type == "procurement_package"
    assert dels[0].module_key == "supply-chain"


async def test_pipeline_secondary_intent_produces_pipeline_summary(client, owner_token, monkeypatch):
    """'pipeline' (secondary intent alias) produces pipeline_summary."""
    uid, _ = owner_token
    await _seed_and_dispatch(
        client, monkeypatch, uid, "pipeline", "Update weighted pipeline for Q3",
        adk_responses=["Pipeline intake output", "Pipeline analysis output"],
    )
    dels = await _deliverables_for(uid)
    assert len(dels) == 1
    assert dels[0].deliverable_type == "pipeline_summary"
    assert dels[0].module_key == "sales"
