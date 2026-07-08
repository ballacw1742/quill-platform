"""SEC: orchestrator service-to-service auth gate (X-Agent-Secret).

The orchestrator's /v1/agents/* tenant routes trust a caller-supplied
tenant_id and have no per-user auth. Because the Cloud Run service is
network-public, they are gated behind a shared X-Agent-Secret that only the
trusted api-bridge holds. Public paths (health, channel webhooks,
/v1/internal/*) are exempt.
"""

import httpx
import pytest

import app.config as config_mod
from app.api import app

SECRET = "s3rvice-secret-under-test"


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def gate_on(monkeypatch):
    """Turn the gate ON by giving get_settings() a secret."""
    orig = config_mod.get_settings
    orig.cache_clear()
    base = orig()

    class _S:
        def __getattr__(self, name):
            return getattr(base, name)

        @property
        def service_auth_secret(self):
            return SECRET

    monkeypatch.setattr(config_mod, "get_settings", lambda: _S())
    # api.py imports get_settings via `from app.config import get_settings`
    import app.api as api_mod

    monkeypatch.setattr(api_mod, "get_settings", lambda: _S())
    yield
    # monkeypatch auto-restores the originals; clear the real cache so later
    # tests re-read fresh settings.
    orig.cache_clear()


async def test_tenant_route_rejected_without_secret(client, gate_on):
    async with client:
        r = await client.get("/v1/agents", params={"tenant_id": "smoke-x"})
    assert r.status_code == 403
    assert "X-Agent-Secret" in r.json()["detail"]


async def test_tenant_route_rejected_with_wrong_secret(client, gate_on):
    async with client:
        r = await client.get(
            "/v1/agents",
            params={"tenant_id": "smoke-x"},
            headers={"X-Agent-Secret": "nope"},
        )
    assert r.status_code == 403


async def test_health_public_even_with_gate_on(client, gate_on):
    async with client:
        r = await client.get("/health")
    # health never requires the secret (may be 200 or 503 on db, never 403)
    assert r.status_code != 403


async def test_channel_webhook_public_even_with_gate_on(client, gate_on):
    async with client:
        r = await client.post(
            "/v1/channels/telegram/webhook",
            json={},
            headers={"content-type": "application/json"},
        )
    # Webhook is exempt from the service gate (self-protected by platform
    # token). It must NOT 403 on the service-auth layer.
    assert r.status_code != 403


async def test_internal_route_exempt_from_service_gate(client, gate_on):
    # /v1/internal/* self-gates on its own secret, so the service gate lets it
    # through; the route's own auth then rejects with 403 for a missing/wrong
    # X-Agent-Secret. Either way it is not blocked by the service-gate layer
    # for the wrong reason — we assert the route-level auth message, not the
    # generic service-gate message.
    async with client:
        r = await client.post("/v1/internal/scheduler/tick")
    assert r.status_code == 403
    # route-level message differs from the service-gate message
    assert "scheduler tick" in r.json()["detail"]
