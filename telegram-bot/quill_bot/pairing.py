"""Pairing code generation + verification for /start <code> flow.

A pairing code is a single-use HMAC-signed token that binds a user (by email)
to a Telegram chat_id when redeemed. The flow:

  1. Charles runs an admin CLI: `quill-bot mint-pair --email charles@...`
     → it prints a code like `Q1.charles@x.com.1715000000.deadbeef...`
  2. Charles opens Telegram and sends `/start Q1....` to @QuillOpsBot
  3. Bot validates HMAC + freshness, calls /v1/admin/users/telegram_pair
     with the email + chat_id, and the User row is updated.

Codes carry their own signature so the bot can validate without DB lookups
or pre-shared per-code state. Codes are valid for 24h by default.

Format: `Q1.<email>.<issued_unix>.<sig>`
   sig = first 16 hex chars of HMAC-SHA256(secret, "Q1|email|issued")
"""

from __future__ import annotations

import hmac
import time
from dataclasses import dataclass
from hashlib import sha256

CODE_VERSION = "Q1"
CODE_TTL_SECONDS = 24 * 3600


@dataclass
class PairingCode:
    email: str
    issued_at: int  # unix seconds
    raw: str


class InvalidPairingCode(ValueError):
    pass


def _sig(secret: str, email: str, issued_at: int) -> str:
    msg = f"{CODE_VERSION}|{email}|{issued_at}".encode()
    return hmac.new(secret.encode(), msg, sha256).hexdigest()[:16]


def mint_code(email: str, secret: str, *, now: int | None = None) -> str:
    """Generate a fresh pairing code for `email`."""
    issued = now if now is not None else int(time.time())
    sig = _sig(secret, email, issued)
    return f"{CODE_VERSION}.{email}.{issued}.{sig}"


def verify_code(
    code: str,
    secret: str,
    *,
    ttl_seconds: int = CODE_TTL_SECONDS,
    now: int | None = None,
) -> PairingCode:
    """Validate a pairing code. Raises InvalidPairingCode on failure.

    Returns the parsed PairingCode on success. Caller is responsible for
    actually doing the DB update.
    """
    parts = code.strip().split(".")
    if len(parts) < 4 or parts[0] != CODE_VERSION:
        raise InvalidPairingCode("malformed code")
    # email may contain dots — rejoin everything between version and the
    # last 2 segments (issued + sig)
    email = ".".join(parts[1:-2])
    try:
        issued = int(parts[-2])
    except ValueError as e:
        raise InvalidPairingCode("bad issued-at") from e
    sig = parts[-1]

    expected = _sig(secret, email, issued)
    if not hmac.compare_digest(sig, expected):
        raise InvalidPairingCode("bad signature")

    now_ts = now if now is not None else int(time.time())
    if now_ts - issued > ttl_seconds:
        raise InvalidPairingCode("expired")
    if issued - now_ts > 60:
        # tolerate a small clock skew but reject codes from the future
        raise InvalidPairingCode("issued in the future")

    return PairingCode(email=email, issued_at=issued, raw=code)
