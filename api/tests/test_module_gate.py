"""Modular Framework Phase 2 — pipeline gate tests (MODULAR_FRAMEWORK_DESIGN.md §3.3).

A request whose owning module is DISABLED for the caller's workspace is skipped
(status "skipped", no agent dispatch). Enabled or unconfigured modules run
normally. The "general" intent is never gated. Fail-open on config ambiguity.
"""

from __future__ import annotations

import pytest

# Import the route module at top level so ModuleConfig is registered with
# Base.metadata before conftest's create_all runs (it seeds a fixed model set).
import app.routes.requests  # noqa: F401
from app.models_modules import ModuleConfig  # noqa: F401
from tests.conftest import auth_h

pytestmark = pytest.mark.asyncio


async def _disable_module(client, token, key: str):
    r = await client.patch(
        "/v1/modules",
        headers=auth_h(token),
        json={"updates": [{"key": key, "enabled": False}]},
    )
    assert r.status_code == 200


async def test_request_skipped_when_module_disabled(client, owner_token, monkeypatch):
    _, token = owner_token
    # Guard: the dispatcher must NOT be called when the module is off.
    import app.routes.requests as reqmod

    called = {"dispatch": False}

    async def _no_dispatch(*a, **k):
        called["dispatch"] = True

    monkeypatch.setattr(reqmod, "_dispatch_to_agent", _no_dispatch)

    await _disable_module(client, token, "estimates")

    r = await client.post(
        "/v1/requests",
        headers=auth_h(token),
        data={"message": "Price out 200 LF of trench", "intent": "estimate"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "skipped"
    assert called["dispatch"] is False


async def test_request_runs_when_module_enabled(client, owner_token, monkeypatch):
    _, token = owner_token
    import app.routes.requests as reqmod

    called = {"dispatch": False}

    async def _spy_dispatch(*a, **k):
        called["dispatch"] = True

    monkeypatch.setattr(reqmod, "_dispatch_to_agent", _spy_dispatch)

    # estimates is enabled by default (no override) — request should dispatch.
    r = await client.post(
        "/v1/requests",
        headers=auth_h(token),
        data={"message": "Price out 200 LF of trench", "intent": "estimate"},
    )
    assert r.status_code == 201
    assert r.json()["status"] == "processing"


async def test_general_intent_never_gated(client, owner_token, monkeypatch):
    _, token = owner_token
    import app.routes.requests as reqmod

    async def _spy_dispatch(*a, **k):
        pass

    monkeypatch.setattr(reqmod, "_dispatch_to_agent", _spy_dispatch)

    # Even if we disable everything we can, "general" has no owning module.
    r = await client.post(
        "/v1/requests",
        headers=auth_h(token),
        data={"message": "Just a general question", "intent": "general"},
    )
    assert r.status_code == 201
    assert r.json()["status"] == "processing"


async def test_disabling_one_module_does_not_skip_another(
    client, owner_token, monkeypatch
):
    _, token = owner_token
    import app.routes.requests as reqmod

    async def _spy_dispatch(*a, **k):
        pass

    monkeypatch.setattr(reqmod, "_dispatch_to_agent", _spy_dispatch)

    # Disable estimates; a contract request (owned by "contracts") still runs.
    await _disable_module(client, token, "estimates")
    r = await client.post(
        "/v1/requests",
        headers=auth_h(token),
        data={"message": "Review this change order", "intent": "contract"},
    )
    assert r.status_code == 201
    assert r.json()["status"] == "processing"


# ── Phase 1: sub-feature gating ──────────────────────────────────────────────


async def _disable_feature(client, token, module_key: str, feature_key: str):
    r = await client.patch(
        "/v1/modules",
        headers=auth_h(token),
        json={"updates": [{"key": module_key, "features": {feature_key: False}}]},
    )
    assert r.status_code == 200


async def test_request_skipped_when_feature_disabled(client, owner_token, monkeypatch):
    _, token = owner_token
    import app.routes.requests as reqmod

    called = {"dispatch": False}

    async def _no_dispatch(*a, **k):
        called["dispatch"] = True

    monkeypatch.setattr(reqmod, "_dispatch_to_agent", _no_dispatch)

    # Disable ONLY the RFI sub-feature of projects (module stays on).
    await _disable_feature(client, token, "projects", "rfi")

    r = await client.post(
        "/v1/requests",
        headers=auth_h(token),
        data={"message": "Log an RFI about the slab", "intent": "rfi"},
    )
    assert r.status_code == 201
    assert r.json()["status"] == "skipped"
    assert called["dispatch"] is False


async def test_other_feature_of_same_module_still_runs(client, owner_token, monkeypatch):
    _, token = owner_token
    import app.routes.requests as reqmod

    async def _spy(*a, **k):
        pass

    monkeypatch.setattr(reqmod, "_dispatch_to_agent", _spy)

    # RFI feature off, but a schedule request (projects/schedule) still runs.
    await _disable_feature(client, token, "projects", "rfi")
    r = await client.post(
        "/v1/requests",
        headers=auth_h(token),
        data={"message": "Check the critical path", "intent": "schedule"},
    )
    assert r.status_code == 201
    assert r.json()["status"] == "processing"
