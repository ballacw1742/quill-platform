"""Shared-workspace access: owner/partner members share all projects and
requests; observers see only their own.

This is the behavior change for the multi-user shared platform — Charles and
the other owner accounts (Khawla, etc.) collaborate in one data space and all
see the same projects.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.enums import UserRole
from app.main import app
from app.security import hash_password, issue_token
from app.models import User
from tests.conftest import auth_h


async def _mk_user(session_maker, email, role):
    async with session_maker() as s:
        u = User(
            email=email,
            display_name=email.split("@")[0],
            role=role,
            password_hash=hash_password("test-pass-123"),
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u.id, issue_token(u)


@pytest.mark.asyncio
async def test_second_owner_sees_first_owners_project(client, owner_token, session_maker):
    """Owner A creates a project; Owner B (a different account) sees it."""
    _, tok_a = owner_token
    r = await client.post(
        "/v1/projects",
        json={"name": "Adams Fork", "description": "shared"},
        headers=auth_h(tok_a),
    )
    assert r.status_code in (200, 201), r.text
    proj_id = r.json()["id"]

    # A different owner account
    _, tok_b = await _mk_user(session_maker, "owner-b@test.local", UserRole.OWNER.value)
    lst = await client.get("/v1/projects", headers=auth_h(tok_b))
    assert lst.status_code == 200, lst.text
    ids = [p["id"] for p in lst.json()["items"]]
    assert proj_id in ids, "second owner should see the shared project"

    # And can open it directly (no 403).
    got = await client.get(f"/v1/projects/{proj_id}", headers=auth_h(tok_b))
    assert got.status_code == 200, got.text


@pytest.mark.asyncio
async def test_partner_sees_shared_project(client, owner_token, partner_token):
    _, tok_a = owner_token
    r = await client.post(
        "/v1/projects", json={"name": "P2"}, headers=auth_h(tok_a)
    )
    proj_id = r.json()["id"]
    _, tok_p = partner_token
    lst = await client.get("/v1/projects", headers=auth_h(tok_p))
    assert proj_id in [p["id"] for p in lst.json()["items"]]


@pytest.mark.asyncio
async def test_observer_does_not_see_others_projects(client, owner_token, session_maker):
    """Observers remain scoped to their own records (not workspace members)."""
    _, tok_a = owner_token
    r = await client.post(
        "/v1/projects", json={"name": "Owner-only"}, headers=auth_h(tok_a)
    )
    proj_id = r.json()["id"]
    _, tok_obs = await _mk_user(session_maker, "obs@test.local", UserRole.OBSERVER.value)
    lst = await client.get("/v1/projects", headers=auth_h(tok_obs))
    assert proj_id not in [p["id"] for p in lst.json()["items"]]
    got = await client.get(f"/v1/projects/{proj_id}", headers=auth_h(tok_obs))
    assert got.status_code == 403
