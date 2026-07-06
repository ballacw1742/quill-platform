"""Sprint 5.5 (G13 / KNOWN_ISSUES #9) — /v1/auth/register gating.

Default posture: ALLOW_SELF_REGISTER=false → anonymous registration is 403;
only an authenticated owner can provision accounts. When the setting is
explicitly enabled (dev/demo), anonymous registrations are clamped to the
observer role. DEV_AUTH_FALLBACK /login behavior is unchanged.
"""

from __future__ import annotations

import pytest
from app.routes import auth as auth_module
from tests.conftest import auth_h

BODY = {
    "email": "newuser@example.com",
    "display_name": "New User",
    "password": "hunter2hunter2",
}


@pytest.mark.asyncio
async def test_anonymous_register_forbidden_by_default(client):
    assert auth_module._settings.ALLOW_SELF_REGISTER is False
    r = await client.post("/v1/auth/register", json=BODY)
    assert r.status_code == 403
    assert "self-registration is disabled" in r.json()["detail"]


@pytest.mark.asyncio
async def test_owner_can_provision_user(client, owner_token):
    _, token = owner_token
    r = await client.post(
        "/v1/auth/register",
        json={**BODY, "role": "partner"},
        headers=auth_h(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == "partner"

    # The provisioned user can log in via the dev fallback (unchanged).
    r = await client.post(
        "/v1/auth/login",
        json={"email": BODY["email"], "password": BODY["password"]},
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_non_owner_cannot_provision(client, owner_token, session_maker):
    # Create an observer directly, then try to use their token to register.
    from app.enums import UserRole
    from app.models import User
    from app.security import hash_password, issue_token

    async with session_maker() as s:
        u = User(
            email="observer@test.local",
            display_name="Observer",
            role=UserRole.OBSERVER.value,
            password_hash=hash_password("test-pass-123"),
        )
        s.add(u)
        await s.commit()
        observer_token = issue_token(u)

    r = await client.post(
        "/v1/auth/register", json=BODY, headers=auth_h(observer_token)
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_self_register_when_enabled_clamps_role(client, monkeypatch):
    monkeypatch.setattr(auth_module._settings, "ALLOW_SELF_REGISTER", True)
    # Anonymous caller asks for owner — must be clamped to observer.
    r = await client.post("/v1/auth/register", json={**BODY, "role": "owner"})
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "observer"


@pytest.mark.asyncio
async def test_invalid_bearer_on_register_is_401_not_silent(client):
    r = await client.post(
        "/v1/auth/register",
        json=BODY,
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code == 401
