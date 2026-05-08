"""WebAuthn passkey ceremonies — Sprint 2.2.

We use a software authenticator (tests/_softauthn.py) so the API exercises
the real py-webauthn verification path end-to-end.
"""

from __future__ import annotations

import base64

from tests._softauthn import SoftAuthn, b64url_decode
from tests.conftest import agent_h, auth_h

RP_ID = "localhost"
ORIGIN = "http://localhost:3000"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _register_passkey(client, token: str, *, name: str = "Test Mac") -> tuple[SoftAuthn, dict]:
    auth = SoftAuthn(rp_id=RP_ID, origin=ORIGIN)

    r = await client.post(
        "/v1/auth/passkey/register/begin",
        json={"attachment": "platform", "name": name},
        headers=auth_h(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    cid = body["ceremony_id"]
    options = body["options"]
    challenge_b64 = options["challenge"]

    response = auth.make_registration_response(challenge_b64)

    r = await client.post(
        "/v1/auth/passkey/register/complete",
        json={"ceremony_id": cid, "response": response, "name": name},
        headers=auth_h(token),
    )
    assert r.status_code == 201, r.text
    return auth, r.json()


async def _login_with_passkey(client, email: str, auth: SoftAuthn) -> str:
    r = await client.post("/v1/auth/passkey/login/begin", json={"email": email})
    assert r.status_code == 200, r.text
    body = r.json()
    cid = body["ceremony_id"]
    challenge_b64 = body["options"]["challenge"]

    response = auth.make_assertion_response(challenge_b64)

    r = await client.post(
        "/v1/auth/passkey/login/complete",
        json={"ceremony_id": cid, "response": response},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _challenge_for_decision(client, token: str, intent: dict, auth: SoftAuthn) -> str:
    r = await client.post(
        "/v1/auth/passkey/challenge/begin",
        json={"action_intent": intent},
        headers=auth_h(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    cid = body["ceremony_id"]
    challenge_b64 = body["options"]["challenge"]

    response = auth.make_assertion_response(challenge_b64)
    r = await client.post(
        "/v1/auth/passkey/challenge/complete",
        json={"ceremony_id": cid, "response": response, "action_intent": intent},
        headers=auth_h(token),
    )
    assert r.status_code == 200, r.text
    return r.json()["auth_assertion"]


SAMPLE_APPROVAL = {
    "agent_id": "rfi-triage",
    "agent_version": "0.1.0",
    "workflow": "rfi.classify",
    "lane": 2,
    "priority": "normal",
    "target_system": "procore",
    "agent_confidence": 0.82,
    "payload": {"rfi_id": "RFI-WA-1", "category": "MEP"},
}


# ---------------------------------------------------------------------------
# 1. Registration ceremony
# ---------------------------------------------------------------------------
async def test_registration_ceremony(client, owner_token):
    _, token = owner_token
    auth, cred = await _register_passkey(client, token)
    assert cred["id"]
    assert cred["name"] == "Test Mac"
    assert cred["attachment"] == "platform"
    assert cred["transports"] in ("internal,hybrid", "internal")

    # Listed under /credentials
    r = await client.get("/v1/auth/passkey/credentials", headers=auth_h(token))
    assert r.status_code == 200
    creds = r.json()
    assert len(creds) == 1
    assert creds[0]["id"] == cred["id"]


# ---------------------------------------------------------------------------
# 2. Login ceremony
# ---------------------------------------------------------------------------
async def test_login_ceremony(client, owner_token, session_maker):
    user_id, token = owner_token
    auth, _ = await _register_passkey(client, token)

    # Look up the email
    from app.models import User

    async with session_maker() as s:
        user = await s.get(User, user_id)
        email = user.email

    new_token = await _login_with_passkey(client, email, auth)
    assert new_token

    # New token should authenticate /auth/me
    r = await client.get("/v1/auth/me", headers=auth_h(new_token))
    assert r.status_code == 200
    assert r.json()["id"] == user_id


# ---------------------------------------------------------------------------
# 3. Action re-auth ceremony — full happy path
# ---------------------------------------------------------------------------
async def test_action_challenge_drives_decision(client, owner_token):
    _, token = owner_token
    auth, _ = await _register_passkey(client, token)

    # Create approval as agent
    r = await client.post("/v1/approvals", json=SAMPLE_APPROVAL, headers=agent_h())
    aid = r.json()["id"]

    intent = {
        "approval_id": aid,
        "decision": "approve",
        "edits": None,
        "rejection_reason": None,
        "escalate_to_lane": None,
    }
    assertion = await _challenge_for_decision(client, token, intent, auth)
    assert assertion.count(".") == 2  # JWT shape

    r = await client.post(
        f"/v1/approvals/{aid}/decide",
        json={"decision": "approve", "auth_assertion": assertion},
        headers=auth_h(token),
    )
    assert r.status_code == 200, r.text
    decided = r.json()
    assert decided["status"] in ("approved", "executed")
    assert decided["records"][0]["auth_method"] == "passkey"


# ---------------------------------------------------------------------------
# 4. Replay attempt rejected
# ---------------------------------------------------------------------------
async def test_action_assertion_rejects_replay(client, owner_token):
    _, token = owner_token
    auth, _ = await _register_passkey(client, token)

    # Two approvals, same user, same intent shape — try to reuse the same assertion.
    r1 = await client.post("/v1/approvals", json=SAMPLE_APPROVAL, headers=agent_h())
    aid1 = r1.json()["id"]
    intent1 = {
        "approval_id": aid1,
        "decision": "approve",
        "edits": None,
        "rejection_reason": None,
        "escalate_to_lane": None,
    }
    assertion = await _challenge_for_decision(client, token, intent1, auth)

    # First use OK
    r = await client.post(
        f"/v1/approvals/{aid1}/decide",
        json={"decision": "approve", "auth_assertion": assertion},
        headers=auth_h(token),
    )
    assert r.status_code == 200

    # Second use of same assertion on a different approval — same shape but new id —
    # must fail because (a) intent_hash mismatches, AND
    # (b) jti was consumed.
    r2 = await client.post("/v1/approvals", json=SAMPLE_APPROVAL, headers=agent_h())
    aid2 = r2.json()["id"]
    r = await client.post(
        f"/v1/approvals/{aid2}/decide",
        json={"decision": "approve", "auth_assertion": assertion},
        headers=auth_h(token),
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# 5. Action intent mismatch
# ---------------------------------------------------------------------------
async def test_action_assertion_intent_mismatch(client, owner_token):
    _, token = owner_token
    auth, _ = await _register_passkey(client, token)

    r = await client.post("/v1/approvals", json=SAMPLE_APPROVAL, headers=agent_h())
    aid = r.json()["id"]
    # Mint a token for "approve" then try to use it for "reject"
    intent_approve = {
        "approval_id": aid,
        "decision": "approve",
        "edits": None,
        "rejection_reason": None,
        "escalate_to_lane": None,
    }
    assertion = await _challenge_for_decision(client, token, intent_approve, auth)

    r = await client.post(
        f"/v1/approvals/{aid}/decide",
        json={"decision": "reject", "rejection_reason": "nope", "auth_assertion": assertion},
        headers=auth_h(token),
    )
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# 6. Multiple passkeys per user
# ---------------------------------------------------------------------------
async def test_multiple_passkeys(client, owner_token):
    _, token = owner_token
    auth1, c1 = await _register_passkey(client, token, name="Mac")
    auth2, c2 = await _register_passkey(client, token, name="iPhone")
    assert c1["id"] != c2["id"]

    r = await client.get("/v1/auth/passkey/credentials", headers=auth_h(token))
    creds = r.json()
    assert {c["name"] for c in creds} == {"Mac", "iPhone"}


# ---------------------------------------------------------------------------
# 7. Credential revocation
# ---------------------------------------------------------------------------
async def test_credential_revocation(client, owner_token, session_maker):
    user_id, token = owner_token
    auth, cred = await _register_passkey(client, token)

    # Email lookup for login
    from app.models import User

    async with session_maker() as s:
        u = await s.get(User, user_id)
        email = u.email

    # Sanity: login works pre-revoke
    await _login_with_passkey(client, email, auth)

    # Revoke
    r = await client.delete(
        f"/v1/auth/passkey/credentials/{cred['id']}", headers=auth_h(token)
    )
    assert r.status_code == 204

    # Login attempt now fails — credential not in allow-list, server returns no match
    r = await client.post("/v1/auth/passkey/login/begin", json={"email": email})
    assert r.status_code == 200
    cid = r.json()["ceremony_id"]
    challenge_b64 = r.json()["options"]["challenge"]
    response = auth.make_assertion_response(challenge_b64)
    r = await client.post(
        "/v1/auth/passkey/login/complete",
        json={"ceremony_id": cid, "response": response},
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# 8. Decide without assertion fails when DEV_AUTH_FALLBACK=false
# ---------------------------------------------------------------------------
async def test_decide_requires_assertion_when_fallback_disabled(
    client, owner_token, monkeypatch
):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "DEV_AUTH_FALLBACK", False)

    _, token = owner_token
    r = await client.post("/v1/approvals", json=SAMPLE_APPROVAL, headers=agent_h())
    aid = r.json()["id"]
    r = await client.post(
        f"/v1/approvals/{aid}/decide",
        json={"decision": "approve"},  # no auth_assertion
        headers=auth_h(token),
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# 9. Challenge fails for users with zero registered passkeys
# ---------------------------------------------------------------------------
async def test_challenge_without_passkeys_412(client, owner_token):
    _, token = owner_token
    r = await client.post(
        "/v1/auth/passkey/challenge/begin",
        json={"action_intent": {"approval_id": "x", "decision": "approve"}},
        headers=auth_h(token),
    )
    assert r.status_code == 412


# ---------------------------------------------------------------------------
# 10. The dev fallback (email/password) still works for Sprint 1 callers
# ---------------------------------------------------------------------------
async def test_dev_fallback_login_still_works(client, owner_token, session_maker):
    user_id, _ = owner_token
    from app.models import User

    async with session_maker() as s:
        u = await s.get(User, user_id)
        email = u.email

    r = await client.post(
        "/v1/auth/login", json={"email": email, "password": "test-pass-123"}
    )
    assert r.status_code == 200
    assert r.json()["access_token"]


# Sanity: base64url decoding helper (we depend on this throughout)
def test_b64url_roundtrip():
    raw = b"\x00\x01\x02hello\xff\xfe"
    enc = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    assert b64url_decode(enc) == raw
