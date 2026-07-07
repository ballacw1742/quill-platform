"""Sprint B1 — per-user tenancy attack suite, api-bridge side
(agent-cloud/TENANCY.md §5, catalog items A1–A5).

Actively attempts cross-tenant violations through the bridge and asserts
they fail: client-supplied tenant_id is ignored on every route, two users
land in two distinct tenants, workspace=org is role-gated, SSE carries the
per-user tenant, and the signup provisioning hook fires (best-effort) on
exactly the user-creation paths.
"""

from __future__ import annotations

import base64
import json
import uuid

import httpx
import pytest
import pytest_asyncio
from app.enums import UserRole
from app.models import User
from app.routes import agent_cloud as bridge
from app.routes import auth as auth_routes
from app.security import hash_password, issue_token

from tests.conftest import auth_h
from tests.test_agent_cloud import KNOWN_SESSION, make_fake_agentcloud

ORG_TENANT = "quill-main"


def user_tenant(uid: str) -> str:
    return f"user-{uid}"


@pytest_asyncio.fixture
async def observer_token(session_maker):
    async with session_maker() as s:
        u = User(
            email="observer@test.local",
            display_name="Observer",
            role=UserRole.OBSERVER.value,
            password_hash=hash_password("test-pass-123"),
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u.id, issue_token(u)


@pytest.fixture
def fake_agentcloud(monkeypatch):
    calls: list = []
    transport = httpx.ASGITransport(app=make_fake_agentcloud(calls))
    monkeypatch.setattr(bridge, "TRANSPORT_OVERRIDE", transport)
    return calls


class _ExplodingTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):  # noqa: D102
        raise httpx.ConnectError("boom", request=request)


ALL_GET_ROUTES = [
    "/v1/agent-cloud/agents",
    "/v1/agent-cloud/sessions",
    f"/v1/agent-cloud/sessions/{KNOWN_SESSION}",
]


# ─── A1: per-user derivation on every route, two users ⇒ two tenants ─────────


@pytest.mark.parametrize("path", ALL_GET_ROUTES)
async def test_get_routes_derive_per_user_tenant(
    client, owner_token, partner_token, fake_agentcloud, path
):
    for uid, token in (owner_token, partner_token):
        fake_agentcloud.clear()
        r = await client.get(path, headers=auth_h(token))
        assert r.status_code == 200
        assert fake_agentcloud[0][1] == user_tenant(uid)


async def test_chat_derives_per_user_tenant(
    client, owner_token, partner_token, fake_agentcloud
):
    for uid, token in (owner_token, partner_token):
        fake_agentcloud.clear()
        r = await client.post(
            "/v1/agent-cloud/chat",
            headers=auth_h(token),
            json={"agent_id": "personal", "message": "hi"},
        )
        assert r.status_code == 200
        assert fake_agentcloud[0][2]["tenant_id"] == user_tenant(uid)
    assert user_tenant(owner_token[0]) != user_tenant(partner_token[0])


# ─── A2: client-supplied tenant_id ignored everywhere ────────────────────────


@pytest.mark.parametrize("path", ALL_GET_ROUTES)
async def test_query_tenant_id_ignored_on_get_routes(
    client, owner_token, fake_agentcloud, path
):
    uid, token = owner_token
    r = await client.get(f"{path}?tenant_id=victim-tenant", headers=auth_h(token))
    assert r.status_code == 200
    assert fake_agentcloud[0][1] == user_tenant(uid)  # not "victim-tenant"


async def test_body_tenant_id_ignored_on_chat(client, owner_token, fake_agentcloud):
    uid, token = owner_token
    r = await client.post(
        "/v1/agent-cloud/chat",
        headers=auth_h(token),
        json={
            "agent_id": "personal",
            "message": "hi",
            "tenant_id": "victim-tenant",
            "stream": True,
        },
    )
    assert r.status_code == 200
    async for _ in r.aiter_bytes():
        pass
    assert fake_agentcloud[0][2]["tenant_id"] == user_tenant(uid)


# ─── A3: workspace=org role gate ──────────────────────────────────────────────


@pytest.mark.parametrize("who", ["owner", "partner"])
async def test_org_workspace_allowed_for_owner_partner(
    client, owner_token, partner_token, fake_agentcloud, who
):
    _, token = owner_token if who == "owner" else partner_token
    r = await client.get(
        "/v1/agent-cloud/agents?workspace=org", headers=auth_h(token)
    )
    assert r.status_code == 200
    assert fake_agentcloud == [("list_agents", ORG_TENANT)]


async def test_org_workspace_forbidden_for_observer(
    client, observer_token, fake_agentcloud
):
    _, token = observer_token
    for path in ALL_GET_ROUTES:
        r = await client.get(f"{path}?workspace=org", headers=auth_h(token))
        assert r.status_code == 403
        assert r.json() == {"detail": "org workspace requires owner or partner role"}
    r = await client.post(
        "/v1/agent-cloud/chat",
        headers=auth_h(token),
        json={"agent_id": "personal", "message": "hi", "workspace": "org"},
    )
    assert r.status_code == 403
    assert fake_agentcloud == []  # nothing ever reached agent-cloud


async def test_org_chat_body_workspace_owner(client, owner_token, fake_agentcloud):
    _, token = owner_token
    r = await client.post(
        "/v1/agent-cloud/chat",
        headers=auth_h(token),
        json={"agent_id": "personal", "message": "hi", "workspace": "org"},
    )
    assert r.status_code == 200
    assert fake_agentcloud[0][2]["tenant_id"] == ORG_TENANT


async def test_workspace_is_an_enum_not_a_tenant_id(client, owner_token, fake_agentcloud):
    """A workspace value that names an arbitrary tenant must 422, never proxy."""
    _, token = owner_token
    r = await client.get(
        "/v1/agent-cloud/agents?workspace=user-somebody-else", headers=auth_h(token)
    )
    assert r.status_code == 422
    r2 = await client.post(
        "/v1/agent-cloud/chat",
        headers=auth_h(token),
        json={"agent_id": "personal", "message": "hi", "workspace": "victim-tenant"},
    )
    assert r2.status_code == 422
    assert fake_agentcloud == []


# ─── A4: SSE stream carries the per-user tenant ──────────────────────────────


async def test_sse_stream_uses_per_user_tenant(client, partner_token, fake_agentcloud):
    uid, token = partner_token
    text = ""
    async with client.stream(
        "POST",
        "/v1/agent-cloud/chat",
        headers=auth_h(token),
        json={"agent_id": "personal", "message": "hi", "stream": True},
    ) as resp:
        assert resp.status_code == 200
        async for chunk in resp.aiter_text():
            text += chunk
    assert "event: done" in text
    assert fake_agentcloud[0][2]["tenant_id"] == user_tenant(uid)


# ─── A5: provisioning hook ────────────────────────────────────────────────────


async def test_provision_user_tenant_calls_agents_read(fake_agentcloud):
    ok = await bridge.provision_user_tenant("abc-123")
    assert ok is True
    assert fake_agentcloud == [("list_agents", "user-abc-123")]


async def test_provision_user_tenant_swallows_outage(monkeypatch):
    monkeypatch.setattr(bridge, "TRANSPORT_OVERRIDE", _ExplodingTransport())
    ok = await bridge.provision_user_tenant("abc-123")
    assert ok is False  # never raises


@pytest.fixture
def provision_spy(monkeypatch):
    calls: list[str] = []

    async def spy(user_id: str) -> bool:
        calls.append(user_id)
        return True

    monkeypatch.setattr(auth_routes, "provision_user_tenant", spy)
    return calls


async def test_register_fires_provisioning_hook(client, owner_token, provision_spy):
    _, token = owner_token
    r = await client.post(
        "/v1/auth/register",
        headers=auth_h(token),  # owner inviter (self-register is gated)
        json={
            "email": "newbie@test.local",
            "password": "test-pass-123",
            "display_name": "Newbie",
            "role": "observer",
        },
    )
    assert r.status_code == 201, r.text
    assert provision_spy == [r.json()["user_id"]]


async def test_register_succeeds_when_agentcloud_down(
    client, owner_token, monkeypatch
):
    """The real hook + a dead agent-cloud: registration still 201s."""
    _, token = owner_token
    monkeypatch.setattr(bridge, "TRANSPORT_OVERRIDE", _ExplodingTransport())
    r = await client.post(
        "/v1/auth/register",
        headers=auth_h(token),
        json={
            "email": "newbie2@test.local",
            "password": "test-pass-123",
            "display_name": "Newbie2",
            "role": "observer",
        },
    )
    assert r.status_code == 201, r.text


async def test_login_does_not_fire_provisioning_hook(
    client, owner_token, provision_spy
):
    _, _token = owner_token
    r = await client.post(
        "/v1/auth/login",
        json={"email": "charles@test.local", "password": "test-pass-123"},
    )
    assert r.status_code == 200
    assert provision_spy == []  # login never creates a user row


def _fake_google_jwt(payload: dict) -> str:
    seg = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJSUzI1NiJ9.{seg}.sig"


class _FakeResponse:
    status_code = 200

    def __init__(self, data: dict):
        self._data = data

    def json(self) -> dict:
        return self._data


async def test_google_first_touch_fires_hook_once(client, monkeypatch, provision_spy):
    email = "google-b1-newbie@example.com"

    async def fake_get(self, url, *args, **kwargs):  # noqa: ANN001
        assert "tokeninfo" in url
        return _FakeResponse({"email": email, "name": "B1 Newbie"})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    token = _fake_google_jwt({"iss": "https://accounts.google.com", "email": email})

    r1 = await client.post("/v1/auth/google", json={"credential": token})
    assert r1.status_code == 200, r1.text
    assert provision_spy == [r1.json()["user_id"]]

    # existing-user sign-in: no second provisioning call
    r2 = await client.post("/v1/auth/google", json={"credential": token})
    assert r2.status_code == 200
    assert provision_spy == [r1.json()["user_id"]]
