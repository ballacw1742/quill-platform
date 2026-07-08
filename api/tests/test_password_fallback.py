"""Password re-auth fallback for approval action-assertions.

Sprint approvals-password-fallback. The passkey ceremony is the primary
re-auth for approval decisions, but after the quillpm.com domain move every
old-RP passkey is orphaned. `POST /v1/auth/password/challenge` mints the SAME
action-assertion JWT the passkey path produces (with `method="password"`), so
`/v1/approvals/{id}/decide` accepts it unchanged.

Covered:
    * good password  -> 200, JWT-shaped assertion, accepted end-to-end by
      /decide, and the decision record's auth_method == "password".
    * bad password   -> 401 "invalid password".
    * no password_hash (SSO-only user) -> 400 with a re-register hint.
    * non-owner/partner -> 403 (authority pre-check mirrors the passkey path).
    * unauthenticated (no bearer) -> 401.
    * rate limit -> the 11th call in a minute is 429 (AUTH_LIMIT, same as login).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import agent_h, auth_h

pytestmark = pytest.mark.asyncio


SAMPLE_APPROVAL = {
    "agent_id": "rfi-triage",
    "agent_version": "0.1.0",
    "workflow": "rfi.classify",
    "lane": 2,
    "priority": "normal",
    "target_system": "procore",
    "agent_confidence": 0.82,
    "payload": {"rfi_id": "RFI-PW-1", "category": "MEP"},
}


async def _new_approval(client: AsyncClient) -> str:
    r = await client.post("/v1/approvals", json=SAMPLE_APPROVAL, headers=agent_h())
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _intent(approval_id: str, decision: str = "approve") -> dict:
    return {
        "approval_id": approval_id,
        "decision": decision,
        "edits": None,
        "rejection_reason": None,
        "escalate_to_lane": None,
    }


# ---------------------------------------------------------------------------
# 1. Happy path — password mints an assertion accepted end-to-end by /decide.
# ---------------------------------------------------------------------------
async def test_password_challenge_drives_decision(client, owner_token):
    _, token = owner_token
    aid = await _new_approval(client)
    intent = _intent(aid)

    r = await client.post(
        "/v1/auth/password/challenge",
        json={"password": "test-pass-123", "action_intent": intent},
        headers=auth_h(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assertion = body["auth_assertion"]
    assert assertion.count(".") == 2  # JWT shape, same as the passkey path
    assert body["expires_in"] == 60

    # The approvals route accepts it with ZERO changes.
    r = await client.post(
        f"/v1/approvals/{aid}/decide",
        json={"decision": "approve", "auth_assertion": assertion},
        headers=auth_h(token),
    )
    assert r.status_code == 200, r.text
    decided = r.json()
    assert decided["status"] in ("approved", "executed")
    # Audit fidelity: password-confirmed decisions are distinguishable forever.
    assert decided["records"][0]["auth_method"] == "password"


# ---------------------------------------------------------------------------
# 2. Wrong password -> 401.
# ---------------------------------------------------------------------------
async def test_password_challenge_wrong_password(client, owner_token):
    _, token = owner_token
    aid = await _new_approval(client)

    r = await client.post(
        "/v1/auth/password/challenge",
        json={"password": "wrong-password", "action_intent": _intent(aid)},
        headers=auth_h(token),
    )
    assert r.status_code == 401, r.text
    assert "invalid password" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 3. SSO-only user (no password_hash) -> 400 with re-register hint.
# ---------------------------------------------------------------------------
async def test_password_challenge_no_password_hash(client, session_maker):
    from app.enums import UserRole
    from app.models import User
    from app.security import issue_token

    async with session_maker() as s:
        u = User(
            email="sso-owner@test.local",
            display_name="SSO Owner",
            role=UserRole.OWNER.value,
            password_hash=None,  # Google-SSO-only
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        token = issue_token(u)

    aid = await _new_approval(client)
    r = await client.post(
        "/v1/auth/password/challenge",
        json={"password": "anything", "action_intent": _intent(aid)},
        headers=auth_h(token),
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"].lower()
    assert "no password" in detail and "passkey" in detail


# ---------------------------------------------------------------------------
# 4. Non-owner/partner -> 403 (authority pre-check).
# ---------------------------------------------------------------------------
async def test_password_challenge_forbidden_for_observer(client, session_maker):
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
        await s.refresh(u)
        token = issue_token(u)

    aid = await _new_approval(client)
    r = await client.post(
        "/v1/auth/password/challenge",
        json={"password": "test-pass-123", "action_intent": _intent(aid)},
        headers=auth_h(token),
    )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 5. Unauthenticated (no bearer session) -> 401.
# ---------------------------------------------------------------------------
async def test_password_challenge_requires_session(client):
    aid = await _new_approval(client)
    r = await client.post(
        "/v1/auth/password/challenge",
        json={"password": "test-pass-123", "action_intent": _intent(aid)},
    )
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# 6. Rate limited at AUTH_LIMIT (10/min per IP), same as /login.
# ---------------------------------------------------------------------------
async def test_password_challenge_rate_limited(client, owner_token):
    _, token = owner_token
    aid = await _new_approval(client)

    # Reset the shared in-memory limiter so this test's window is clean and we
    # don't inherit counters from earlier tests (or leak to later ones).
    from app.rate_limit import limiter

    try:
        limiter.reset()
    except Exception:  # noqa: BLE001 — best-effort; storage may not expose reset
        pass

    payload = {"password": "wrong-password", "action_intent": _intent(aid)}
    statuses = []
    for _ in range(12):
        r = await client.post(
            "/v1/auth/password/challenge", json=payload, headers=auth_h(token)
        )
        statuses.append(r.status_code)

    # First 10 are processed (401 wrong password); the limiter trips after that.
    assert 429 in statuses, statuses
    assert statuses[:10] == [401] * 10, statuses

    # Clean up so subsequent tests in this process aren't rate-limited.
    try:
        limiter.reset()
    except Exception:  # noqa: BLE001
        pass
