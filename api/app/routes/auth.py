"""Auth routes. Sprint 1: dev email+password. Sprint 2: WebAuthn passkeys."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User
from app.schemas import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.security import get_current_user, hash_password, issue_token, verify_password

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenOut:
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    user = User(
        email=body.email,
        display_name=body.display_name,
        role=body.role.value if hasattr(body.role, "value") else str(body.role),
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return TokenOut(access_token=issue_token(user), user_id=user.id, role=user.role)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenOut:
    res = await db.execute(select(User).where(User.email == body.email))
    user = res.scalars().first()
    if user is None or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return TokenOut(access_token=issue_token(user), user_id=user.id, role=user.role)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


# ---------------------------------------------------------------------------
# WebAuthn — Sprint 2 will fill these in. Stubs raise NotImplementedError so
# callers fail loudly rather than silently.
# ---------------------------------------------------------------------------
@router.post("/webauthn/register/begin")
async def webauthn_register_begin() -> None:
    raise NotImplementedError("WebAuthn registration arrives in Sprint 2.")


@router.post("/webauthn/register/finish")
async def webauthn_register_finish() -> None:
    raise NotImplementedError("WebAuthn registration arrives in Sprint 2.")


@router.post("/webauthn/assert/begin")
async def webauthn_assert_begin() -> None:
    raise NotImplementedError("WebAuthn assertion arrives in Sprint 2.")


@router.post("/webauthn/assert/finish")
async def webauthn_assert_finish() -> None:
    raise NotImplementedError("WebAuthn assertion arrives in Sprint 2.")
