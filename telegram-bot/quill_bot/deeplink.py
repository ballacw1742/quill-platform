"""Ephemeral deep links to the web UI's passkey challenge.

Telegram cannot perform a WebAuthn ceremony — we always punt to the browser.
A deep link is a signed, short-lived URL that opens the web UI directly to
the passkey approval page for one specific approval ID + intent
(approve | reject | edit).

Anatomy of a deep link payload (URL-encoded, then signed):
    {
      "id": "<approval_id>",
      "intent": "approve" | "reject" | "edit",
      "user_id": "<charles user_id>",
      "exp": <unix_seconds>,
      "nonce": "<8-byte hex>"
    }

Signed with HMAC-SHA256(deeplink_signing_secret, canonical_json).

Default TTL: 60 seconds (matches ACTION_ASSERTION_TTL_SECONDS so the assertion
the user picks up *also* expires within that window — no wider window for an
attacker if a link leaks).
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from urllib.parse import quote

Intent = Literal["approve", "reject", "edit"]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sig(payload_bytes: bytes, secret: str) -> str:
    return _b64url(hmac.new(secret.encode(), payload_bytes, sha256).digest())


@dataclass
class DeepLinkPayload:
    id: str
    intent: Intent
    user_id: str | None
    exp: int
    nonce: str


def make(
    approval_id: str,
    intent: Intent,
    *,
    secret: str,
    base_url: str,
    user_id: str | None = None,
    ttl_seconds: int = 60,
    extra: dict | None = None,
    now: int | None = None,
) -> str:
    """Generate a signed deep link URL.

    Resulting URL shape:
        {base_url}/approvals/{id}/{intent}?t=<token>

    The token is base64url(canonical_json) + "." + base64url(sig).
    """
    issued = now if now is not None else int(time.time())
    payload: dict = {
        "id": approval_id,
        "intent": intent,
        "user_id": user_id,
        "exp": issued + ttl_seconds,
        "nonce": _b64url(os.urandom(8)),
    }
    if extra:
        payload["extra"] = extra
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload_b64 = _b64url(canonical.encode("utf-8"))
    sig = _sig(canonical.encode("utf-8"), secret)
    token = f"{payload_b64}.{sig}"
    return f"{base_url.rstrip('/')}/approvals/{quote(approval_id)}/{intent}?t={token}"


def verify(
    token: str,
    *,
    secret: str,
    now: int | None = None,
) -> DeepLinkPayload:
    """Parse + validate a deep-link token.

    Raises ValueError on invalid format, signature, or expiry.
    """
    if "." not in token:
        raise ValueError("malformed token")
    payload_b64, sig = token.rsplit(".", 1)
    canonical = _b64url_decode(payload_b64)
    expected = _sig(canonical, secret)
    if not hmac.compare_digest(sig, expected):
        raise ValueError("bad signature")
    data = json.loads(canonical)
    now_ts = now if now is not None else int(time.time())
    if now_ts > int(data["exp"]):
        raise ValueError("expired")
    return DeepLinkPayload(
        id=data["id"],
        intent=data["intent"],
        user_id=data.get("user_id"),
        exp=int(data["exp"]),
        nonce=data.get("nonce", ""),
    )
