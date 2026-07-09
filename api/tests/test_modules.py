"""Modular framework Phase 0 — module config route tests.

Covers: default (no overrides) returns the full roster enabled in roster order;
owner can disable + reorder; non-owner is 403 on mutate; unknown key 400; auth
required; personal vs org workspace isolation.
"""

from __future__ import annotations

import pytest

from app.routes.modules import MODULE_ROSTER
from tests.conftest import auth_h

pytestmark = pytest.mark.asyncio

ROSTER_KEYS = [m["key"] for m in MODULE_ROSTER]


async def test_requires_auth(client):
    r = await client.get("/v1/modules")
    assert r.status_code in (401, 403)


async def test_default_returns_full_roster_enabled_in_order(client, owner_token):
    _, token = owner_token
    r = await client.get("/v1/modules", headers=auth_h(token))
    assert r.status_code == 200
    items = r.json()["items"]
    # All 15 present, all enabled, in roster order (zero behavior change).
    assert [i["key"] for i in items] == ROSTER_KEYS
    assert all(i["enabled"] for i in items)


async def test_owner_can_disable_a_module(client, owner_token):
    _, token = owner_token
    r = await client.patch(
        "/v1/modules",
        headers=auth_h(token),
        json={"updates": [{"key": "finance", "enabled": False}]},
    )
    assert r.status_code == 200
    items = {i["key"]: i for i in r.json()["items"]}
    assert items["finance"]["enabled"] is False
    # everything else stays enabled
    assert items["projects"]["enabled"] is True
    # persists on re-read
    r2 = await client.get("/v1/modules", headers=auth_h(token))
    assert {i["key"]: i["enabled"] for i in r2.json()["items"]}["finance"] is False


async def test_owner_can_reorder(client, owner_token):
    _, token = owner_token
    # Pin agents to order 0 (front); it normally sorts last in the roster.
    r = await client.patch(
        "/v1/modules",
        headers=auth_h(token),
        json={"updates": [{"key": "agents", "sort_order": 0}]},
    )
    assert r.status_code == 200
    # agents (override order 0) now ties with requests (roster order 0); the
    # secondary sort is roster order, so requests(0) then agents(14-roster)
    # — assert agents moved ahead of everything with roster order > 0.
    keys = [i["key"] for i in r.json()["items"]]
    assert keys.index("agents") <= 1  # front of the list
    assert keys.index("agents") < keys.index("finance")


async def test_non_owner_cannot_mutate(client, partner_token):
    _, token = partner_token
    r = await client.patch(
        "/v1/modules",
        headers=auth_h(token),
        json={"updates": [{"key": "finance", "enabled": False}]},
    )
    assert r.status_code == 403
    # partner can still READ
    rget = await client.get("/v1/modules", headers=auth_h(token))
    assert rget.status_code == 200


async def test_unknown_key_400(client, owner_token):
    _, token = owner_token
    r = await client.patch(
        "/v1/modules",
        headers=auth_h(token),
        json={"updates": [{"key": "not-a-module", "enabled": False}]},
    )
    assert r.status_code == 400


async def test_personal_and_org_are_isolated(client, owner_token):
    _, token = owner_token
    # Disable finance in personal only.
    await client.patch(
        "/v1/modules",
        headers=auth_h(token),
        json={"updates": [{"key": "finance", "enabled": False}], "workspace": "personal"},
    )
    org = await client.get("/v1/modules?workspace=org", headers=auth_h(token))
    org_finance = {i["key"]: i["enabled"] for i in org.json()["items"]}["finance"]
    # org workspace unaffected — still enabled
    assert org_finance is True


# ── Phase 1: sub-feature toggles ─────────────────────────────────────────────


async def test_get_includes_feature_catalog(client, owner_token):
    _, token = owner_token
    r = await client.get("/v1/modules", headers=auth_h(token))
    items = {i["key"]: i for i in r.json()["items"]}
    # contracts has a fixed feature list, all enabled by default
    feats = {f["key"]: f["enabled"] for f in items["contracts"]["features"]}
    assert "change_orders" in feats and all(feats.values())
    # a module with no sub-features has an empty list
    assert items["approvals"]["features"] == []


async def test_owner_can_disable_a_feature(client, owner_token):
    _, token = owner_token
    r = await client.patch(
        "/v1/modules",
        headers=auth_h(token),
        json={"updates": [{"key": "contracts", "features": {"e_sign": False}}]},
    )
    assert r.status_code == 200
    items = {i["key"]: i for i in r.json()["items"]}
    feats = {f["key"]: f["enabled"] for f in items["contracts"]["features"]}
    assert feats["e_sign"] is False
    assert feats["change_orders"] is True  # others unaffected
    # module itself stays enabled
    assert items["contracts"]["enabled"] is True


async def test_unknown_feature_key_400(client, owner_token):
    _, token = owner_token
    r = await client.patch(
        "/v1/modules",
        headers=auth_h(token),
        json={"updates": [{"key": "contracts", "features": {"nope": False}}]},
    )
    assert r.status_code == 400
