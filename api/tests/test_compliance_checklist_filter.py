"""Sprint 5.5 (G10) — GET /v1/compliance/checklists?campus_id=… filter.

KNOWN_ISSUES #4: rows carry campus_id but the list endpoint silently
ignored the query param. These tests pin the fix.
"""

from __future__ import annotations

import pytest
from app import models_compliance  # noqa: F401 — register tables before create_all
from tests.conftest import auth_h


async def _mk_checklist(client, token: str, name: str, campus_id: str | None):
    r = await client.post(
        "/v1/compliance/checklists",
        headers=auth_h(token),
        json={
            "name": name,
            "framework": "soc2",
            "campus_id": campus_id,
            "status": "active",
            "items": [
                {"control_id": "CC1.1", "title": "Control environment"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_checklists_filter_by_campus_id(client, owner_token):
    _, token = owner_token
    await _mk_checklist(client, token, "Campus A SOC2", "campus-aaa")
    await _mk_checklist(client, token, "Campus B SOC2", "campus-bbb")
    await _mk_checklist(client, token, "Org-wide SOC2", None)

    # Unfiltered: all three
    r = await client.get("/v1/compliance/checklists", headers=auth_h(token))
    assert r.status_code == 200
    assert r.json()["total"] == 3

    # Filtered: only campus A
    r = await client.get(
        "/v1/compliance/checklists?campus_id=campus-aaa", headers=auth_h(token)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "Campus A SOC2"
    assert body["items"][0]["campus_id"] == "campus-aaa"

    # Filtered: unknown campus → empty, not error
    r = await client.get(
        "/v1/compliance/checklists?campus_id=campus-zzz", headers=auth_h(token)
    )
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["items"] == []


@pytest.mark.asyncio
async def test_checklists_campus_filter_composes_with_framework(client, owner_token):
    _, token = owner_token
    await _mk_checklist(client, token, "A soc2", "campus-aaa")
    r = await client.post(
        "/v1/compliance/checklists",
        headers=auth_h(token),
        json={"name": "A iso", "framework": "iso27001", "campus_id": "campus-aaa", "status": "active"},
    )
    assert r.status_code == 201, r.text

    r = await client.get(
        "/v1/compliance/checklists?campus_id=campus-aaa&framework=iso27001",
        headers=auth_h(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["framework"] == "iso27001"
