"""Sprint 5.5 — /v1/auth/google first-sign-in auto-create.

Regression test for the AttributeError (`UserRole.observer` doesn't exist)
that 500'd every brand-new Google sign-in. Existing-user sign-ins never hit
the create branch, which is why this stayed hidden.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest


def _fake_google_jwt(payload: dict) -> str:
    seg = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJSUzI1NiJ9.{seg}.sig"


class _FakeResponse:
    status_code = 200

    def __init__(self, data: dict):
        self._data = data

    def json(self) -> dict:
        return self._data


@pytest.mark.asyncio
async def test_google_first_signin_creates_observer(client, monkeypatch):
    email = "brand-new-google-user@example.com"

    async def fake_get(self, url, *args, **kwargs):  # noqa: ANN001
        assert "tokeninfo" in url
        return _FakeResponse({"email": email, "name": "New Google User"})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    token = _fake_google_jwt({"iss": "https://accounts.google.com", "email": email})
    r = await client.post("/v1/auth/google", json={"credential": token})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "observer"
    assert body["access_token"]

    # Second sign-in reuses the row (no duplicate) and still succeeds.
    r2 = await client.post("/v1/auth/google", json={"credential": token})
    assert r2.status_code == 200, r2.text
    assert r2.json()["user_id"] == body["user_id"]
