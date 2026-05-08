"""Auth/security helpers — Sprint 1 dev tokens; Sprint 2 will harden with WebAuthn."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.enums import UserRole
from app.models import User

_settings = get_settings()

ALGO = "HS256"
TOKEN_TTL = timedelta(hours=12)


def _truncate(plain: str) -> bytes:
    # bcrypt has a hard 72-byte limit; truncate consistently.
    return plain.encode("utf-8")[:72]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_truncate(plain), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


def issue_token(user: User) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + TOKEN_TTL).timestamp()),
    }
    return jwt.encode(payload, _settings.SECRET_KEY, algorithm=ALGO)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, _settings.SECRET_KEY, algorithms=[ALGO])
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {exc}") from exc


def _bearer(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    parts = auth_header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "malformed token")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return user


async def require_owner(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.OWNER.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner role required")
    return user


def require_agent_secret(
    x_agent_secret: str | None = Header(default=None, alias="X-Agent-Secret"),
) -> str:
    """Sprint 1 service-account auth: shared secret for agents."""
    if not x_agent_secret or not hmac.compare_digest(
        x_agent_secret, _settings.AGENT_SHARED_SECRET
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid agent secret")
    return "agent:service-account"


def require_admin_header(
    x_admin: str | None = Header(default=None, alias="X-Admin"),
) -> str:
    """Sprint 1 admin gate: header check. Sprint 2 will require owner JWT."""
    if not x_admin or not hmac.compare_digest(x_admin, _settings.AGENT_SHARED_SECRET):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "admin header missing/invalid")
    return "admin:header"
