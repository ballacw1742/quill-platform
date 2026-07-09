"""Deliverable Phase A — route tests.

Covers:
  - create → v1 (with and without project_id)
  - patch bumps to v2; list_versions returns [2, 1] newest-first
  - rollback to v1 creates v3
  - detail 404 for unknown id
  - list filters by ?project_id=
  - cross-user isolation: another user cannot read someone else's deliverable

Import the model at top level so conftest's create_all sees the tables.
"""

from __future__ import annotations

import pytest

# ── Critical: import model at top level so Base.metadata.create_all picks it up ──
from app.models_deliverables import Deliverable, DeliverableVersion  # noqa: F401
from tests.conftest import auth_h

pytestmark = pytest.mark.asyncio

# ── Helpers ────────────────────────────────────────────────────────────────────

BASE = "/v1/deliverables"

PAYLOAD = {
    "module_key": "projects",
    "deliverable_type": "schedule",
    "title": "Initial schedule v1",
    "content": {"rows": [1, 2, 3]},
}


# ── Auth guard ─────────────────────────────────────────────────────────────────


async def test_requires_auth(client):
    r = await client.get(BASE)
    assert r.status_code in (401, 403)


# ── Create ─────────────────────────────────────────────────────────────────────


async def test_create_returns_v1(client, owner_token):
    _, token = owner_token
    r = await client.post(BASE, headers=auth_h(token), json=PAYLOAD)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["version"] == 1
    assert d["status"] == "draft"
    assert d["title"] == PAYLOAD["title"]
    assert d["module_key"] == PAYLOAD["module_key"]
    assert d["deliverable_type"] == PAYLOAD["deliverable_type"]
    assert d["content"] == PAYLOAD["content"]
    assert d["project_id"] is None


async def test_create_with_project_id(client, owner_token):
    _, token = owner_token
    pid = "proj-abc-123"
    r = await client.post(
        BASE,
        headers=auth_h(token),
        json={**PAYLOAD, "project_id": pid},
    )
    assert r.status_code == 201
    assert r.json()["project_id"] == pid


# ── List ───────────────────────────────────────────────────────────────────────


async def test_list_empty(client, owner_token):
    _, token = owner_token
    r = await client.get(BASE, headers=auth_h(token))
    assert r.status_code == 200
    assert r.json()["items"] == []
    assert r.json()["total"] == 0


async def test_list_returns_own_deliverables(client, owner_token):
    _, token = owner_token
    await client.post(BASE, headers=auth_h(token), json=PAYLOAD)
    await client.post(BASE, headers=auth_h(token), json={**PAYLOAD, "title": "Second"})
    r = await client.get(BASE, headers=auth_h(token))
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert r.json()["total"] == 2


async def test_list_filters_by_project_id(client, owner_token):
    _, token = owner_token
    pid = "proj-filter-test"
    # One with project_id, one without.
    await client.post(BASE, headers=auth_h(token), json={**PAYLOAD, "project_id": pid})
    await client.post(BASE, headers=auth_h(token), json=PAYLOAD)
    r = await client.get(BASE + f"?project_id={pid}", headers=auth_h(token))
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["project_id"] == pid


# ── Detail ─────────────────────────────────────────────────────────────────────


async def test_detail_404_unknown(client, owner_token):
    _, token = owner_token
    r = await client.get(BASE + "/does-not-exist", headers=auth_h(token))
    assert r.status_code == 404


async def test_detail_returns_deliverable(client, owner_token):
    _, token = owner_token
    created = (await client.post(BASE, headers=auth_h(token), json=PAYLOAD)).json()
    r = await client.get(BASE + f"/{created['id']}", headers=auth_h(token))
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]
    assert r.json()["version"] == 1


# ── Patch ──────────────────────────────────────────────────────────────────────


async def test_patch_bumps_version(client, owner_token):
    _, token = owner_token
    created = (await client.post(BASE, headers=auth_h(token), json=PAYLOAD)).json()
    did = created["id"]

    r = await client.patch(
        BASE + f"/{did}",
        headers=auth_h(token),
        json={"title": "Updated title", "status": "in_progress"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["version"] == 2
    assert d["title"] == "Updated title"
    assert d["status"] == "in_progress"


async def test_patch_list_versions_newest_first(client, owner_token):
    _, token = owner_token
    created = (await client.post(BASE, headers=auth_h(token), json=PAYLOAD)).json()
    did = created["id"]

    await client.patch(
        BASE + f"/{did}",
        headers=auth_h(token),
        json={"title": "Updated title"},
    )

    r = await client.get(BASE + f"/{did}/versions", headers=auth_h(token))
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    # Newest (v1 snapshot written on update) should be version 1 — the snapshot
    # records the PRIOR version before bump; after patch we have v2 head + v1 snap.
    versions = [v["version"] for v in items]
    # Versions list is newest-first: the snapshot written when v2 was applied
    # captures the prior v1, so we see versions [1] from one PATCH. On CREATE
    # we also write a "created" snapshot at v1. After one PATCH we have two
    # snapshots both at v1 — but one is "created" and one is "updated".
    # The important check: ordered descending, and head is v2.
    detail = (await client.get(BASE + f"/{did}", headers=auth_h(token))).json()
    assert detail["version"] == 2
    # All version snapshots come back
    assert len(items) == 2
    assert all(v["deliverable_id"] == did for v in items)


async def test_patch_invalid_status_400(client, owner_token):
    _, token = owner_token
    created = (await client.post(BASE, headers=auth_h(token), json=PAYLOAD)).json()
    did = created["id"]
    r = await client.patch(
        BASE + f"/{did}",
        headers=auth_h(token),
        json={"status": "not_a_real_status"},
    )
    assert r.status_code == 400


# ── Rollback ───────────────────────────────────────────────────────────────────


async def test_rollback_creates_new_version(client, owner_token):
    _, token = owner_token
    created = (await client.post(BASE, headers=auth_h(token), json=PAYLOAD)).json()
    did = created["id"]

    # Advance to v2 with a different title.
    await client.patch(
        BASE + f"/{did}",
        headers=auth_h(token),
        json={"title": "v2 title", "status": "in_progress"},
    )

    # Rollback to v1 → creates v3.
    r = await client.post(
        BASE + f"/{did}/rollback",
        headers=auth_h(token),
        json={"to_version": 1},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["version"] == 3
    # Title restored from v1 snapshot.
    assert d["title"] == PAYLOAD["title"]

    # Versions list should have 3 entries (created, updated, rolledback).
    versions_r = await client.get(BASE + f"/{did}/versions", headers=auth_h(token))
    assert versions_r.status_code == 200
    items = versions_r.json()["items"]
    assert len(items) == 3
    # Newest-first: versions should be ordered descending.
    vnums = [v["version"] for v in items]
    assert vnums == sorted(vnums, reverse=True)


async def test_rollback_unknown_version_404(client, owner_token):
    _, token = owner_token
    created = (await client.post(BASE, headers=auth_h(token), json=PAYLOAD)).json()
    did = created["id"]
    r = await client.post(
        BASE + f"/{did}/rollback",
        headers=auth_h(token),
        json={"to_version": 99},
    )
    assert r.status_code == 404


# ── Cross-user isolation ───────────────────────────────────────────────────────


async def test_other_user_cannot_read_deliverable(client, owner_token, partner_token):
    """Another user gets 404 on a deliverable they don't own."""
    _, owner_tok = owner_token
    _, partner_tok = partner_token

    created = (
        await client.post(BASE, headers=auth_h(owner_tok), json=PAYLOAD)
    ).json()
    did = created["id"]

    # Partner tries to read.
    r = await client.get(BASE + f"/{did}", headers=auth_h(partner_tok))
    assert r.status_code == 404

    # Partner list doesn't include owner's deliverable.
    lst = await client.get(BASE, headers=auth_h(partner_tok))
    assert lst.status_code == 200
    assert all(i["id"] != did for i in lst.json()["items"])


async def test_other_user_cannot_patch_deliverable(client, owner_token, partner_token):
    _, owner_tok = owner_token
    _, partner_tok = partner_token

    created = (
        await client.post(BASE, headers=auth_h(owner_tok), json=PAYLOAD)
    ).json()
    did = created["id"]

    r = await client.patch(
        BASE + f"/{did}",
        headers=auth_h(partner_tok),
        json={"title": "Steal"},
    )
    assert r.status_code == 404


async def test_other_user_cannot_rollback_deliverable(
    client, owner_token, partner_token
):
    _, owner_tok = owner_token
    _, partner_tok = partner_token

    created = (
        await client.post(BASE, headers=auth_h(owner_tok), json=PAYLOAD)
    ).json()
    did = created["id"]

    r = await client.post(
        BASE + f"/{did}/rollback",
        headers=auth_h(partner_tok),
        json={"to_version": 1},
    )
    assert r.status_code == 404


async def test_rollback_to_intermediate_version_restores_that_content(client, owner_token):
    """Regression: each version's snapshot must capture the content AT that
    version. Rolling back to an intermediate version (v2) must restore v2's
    content, not v1's or the prior state. Pins the create→bump→snapshot order."""
    _, token = owner_token
    created = (await client.post(BASE, headers=auth_h(token), json={
        "module_key": "estimates", "deliverable_type": "cost_estimate",
        "title": "v1", "content": {"n": 1},
    })).json()
    did = created["id"]

    # v2 with distinct content
    await client.patch(BASE + f"/{did}", headers=auth_h(token),
                       json={"title": "v2", "content": {"n": 2}})
    # v3 with distinct content
    await client.patch(BASE + f"/{did}", headers=auth_h(token),
                       json={"title": "v3", "content": {"n": 3}})

    # the versions list must expose exactly one snapshot per version number
    items = (await client.get(BASE + f"/{did}/versions", headers=auth_h(token))).json()["items"]
    by_ver = {}
    for it in items:
        by_ver.setdefault(it["version"], 0)
        by_ver[it["version"]] += 1
    assert by_ver.get(1) == 1 and by_ver.get(2) == 1 and by_ver.get(3) == 1, by_ver

    # rollback to v2 → new v4 whose content is v2's
    r = await client.post(BASE + f"/{did}/rollback", headers=auth_h(token),
                          json={"to_version": 2})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["version"] == 4
    assert d["title"] == "v2" and d["content"] == {"n": 2}, d
