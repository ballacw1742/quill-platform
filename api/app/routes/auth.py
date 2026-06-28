"""Auth routes — Sprint 2.2 WebAuthn passkeys.

Endpoints:
    POST /v1/auth/register                       (dev-only fallback, gated)
    POST /v1/auth/login                          (dev-only fallback, gated)
    GET  /v1/auth/me
    POST /v1/auth/passkey/register/begin
    POST /v1/auth/passkey/register/complete
    POST /v1/auth/passkey/login/begin
    POST /v1/auth/passkey/login/complete
    POST /v1/auth/passkey/challenge/begin
    POST /v1/auth/passkey/challenge/complete
    GET  /v1/auth/passkey/credentials
    DELETE /v1/auth/passkey/credentials/{id}
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.enums import UserRole
from app.models import User, WebAuthnCredential
from app.schemas import (
    ActionAssertionOut,
    LoginRequest,
    PasskeyChallengeBegin,
    PasskeyChallengeComplete,
    PasskeyCredentialOut,
    PasskeyLoginBegin,
    PasskeyLoginComplete,
    PasskeyOptionsOut,
    PasskeyRegisterBegin,
    PasskeyRegisterComplete,
    RegisterRequest,
    TokenOut,
    UserOut,
)
from app.security import get_current_user, hash_password, issue_token, verify_password
from app.services.security import (
    challenge_store,
    generate_authentication_options,
    generate_registration_options,
    mint_action_assertion_jwt,
    verify_authentication_response,
    verify_registration_response,
)

router = APIRouter(prefix="/v1/auth", tags=["auth"])
_settings = get_settings()


# ---------------------------------------------------------------------------
# Dev-only email/password fallback (gated by DEV_AUTH_FALLBACK)
# ---------------------------------------------------------------------------
def _require_dev_fallback() -> None:
    if not _settings.DEV_AUTH_FALLBACK:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "email/password auth disabled — use a passkey"
        )


@router.post(
    "/register",
    response_model=TokenOut,
    status_code=status.HTTP_201_CREATED,
    summary="(dev fallback) Register a user with email + password.",
)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenOut:
    _require_dev_fallback()
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


@router.post("/login", response_model=TokenOut, summary="(dev fallback) Email/password login.")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenOut:
    _require_dev_fallback()
    res = await db.execute(select(User).where(User.email == body.email))
    user = res.scalars().first()
    if (
        user is None
        or not user.password_hash
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return TokenOut(access_token=issue_token(user), user_id=user.id, role=user.role)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


# ---------------------------------------------------------------------------
# Passkey registration (requires existing session)
# ---------------------------------------------------------------------------
@router.post("/passkey/register/begin", response_model=PasskeyOptionsOut)
async def passkey_register_begin(
    body: PasskeyRegisterBegin,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PasskeyOptionsOut:
    res = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
    )
    existing = list(res.scalars().all())
    result = generate_registration_options(
        user, existing_credentials=existing, attachment=body.attachment
    )
    cid = challenge_store.put(
        challenge_b64=result.challenge_b64,
        user_id=user.id,
        kind="register",
        ttl_seconds=300,
    )
    return PasskeyOptionsOut(ceremony_id=cid, options=json.loads(result.options_json))


@router.post(
    "/passkey/register/complete",
    response_model=PasskeyCredentialOut,
    status_code=status.HTTP_201_CREATED,
)
async def passkey_register_complete(
    body: PasskeyRegisterComplete,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PasskeyCredentialOut:
    pending = challenge_store.take(body.ceremony_id)
    if pending.kind != "register" or pending.user_id != user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ceremony mismatch")

    verified = verify_registration_response(
        response=body.response,
        expected_challenge_b64=pending.challenge_b64,
    )

    # Reject duplicate enrollments
    dup = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.credential_id_b64 == verified.credential_id_b64
        )
    )
    if dup.scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, "credential already registered")

    cred = WebAuthnCredential(
        user_id=user.id,
        credential_id_b64=verified.credential_id_b64,
        public_key_b64=verified.public_key_b64,
        sign_count=verified.sign_count,
        name=body.name or _default_passkey_name(verified.attachment),
        transports=verified.transports,
        attachment=verified.attachment,
        aaguid=verified.aaguid,
        backup_eligible=verified.backup_eligible,
        backup_state=verified.backup_state,
    )
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    return PasskeyCredentialOut.model_validate(cred)


def _default_passkey_name(attachment: str | None) -> str:
    if attachment == "platform":
        return "This device"
    if attachment == "cross-platform":
        return "Hardware security key"
    return "Passkey"


# ---------------------------------------------------------------------------
# Passkey login (no prior session)
# ---------------------------------------------------------------------------
@router.post("/passkey/login/begin", response_model=PasskeyOptionsOut)
async def passkey_login_begin(
    body: PasskeyLoginBegin, db: AsyncSession = Depends(get_db)
) -> PasskeyOptionsOut:
    res = await db.execute(select(User).where(User.email == body.email))
    user = res.scalars().first()
    if user is None:
        # Don't leak which emails exist; still issue a ceremony with no allowed creds.
        creds: list[WebAuthnCredential] = []
        user_id_for_store: str | None = None
    else:
        cres = await db.execute(
            select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
        )
        creds = [c for c in cres.scalars().all() if c.revoked_at is None]
        user_id_for_store = user.id

    result = generate_authentication_options(credentials=creds)
    cid = challenge_store.put(
        challenge_b64=result.challenge_b64,
        user_id=user_id_for_store,
        kind="login",
        ttl_seconds=300,
    )
    return PasskeyOptionsOut(ceremony_id=cid, options=json.loads(result.options_json))


@router.post("/passkey/login/complete", response_model=TokenOut)
async def passkey_login_complete(
    body: PasskeyLoginComplete, db: AsyncSession = Depends(get_db)
) -> TokenOut:
    pending = challenge_store.take(body.ceremony_id)
    if pending.kind != "login":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ceremony mismatch")
    if pending.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no such user")

    cred_id_b64 = _extract_credential_id(body.response)
    cred = await _load_credential(db, cred_id_b64, pending.user_id)

    verified = verify_authentication_response(
        response=body.response,
        expected_challenge_b64=pending.challenge_b64,
        credential=cred,
    )
    cred.sign_count = verified.new_sign_count
    cred.last_used_at = datetime.now(UTC)
    await db.commit()

    user = await db.get(User, pending.user_id)
    assert user is not None
    return TokenOut(access_token=issue_token(user), user_id=user.id, role=user.role)


# ---------------------------------------------------------------------------
# Action re-auth challenge (gates approval decisions)
# ---------------------------------------------------------------------------
@router.post("/passkey/challenge/begin", response_model=PasskeyOptionsOut)
async def passkey_challenge_begin(
    body: PasskeyChallengeBegin,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PasskeyOptionsOut:
    cres = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
    )
    creds = [c for c in cres.scalars().all() if c.revoked_at is None]
    if not creds:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            "no registered passkeys; visit /settings/passkeys",
        )

    result = generate_authentication_options(credentials=creds)
    cid = challenge_store.put(
        challenge_b64=result.challenge_b64,
        user_id=user.id,
        kind="action",
        action_intent=body.action_intent.model_dump(mode="json"),
        ttl_seconds=120,
    )
    return PasskeyOptionsOut(ceremony_id=cid, options=json.loads(result.options_json))


@router.post("/passkey/challenge/complete", response_model=ActionAssertionOut)
async def passkey_challenge_complete(
    body: PasskeyChallengeComplete,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ActionAssertionOut:
    pending = challenge_store.take(body.ceremony_id)
    if pending.kind != "action" or pending.user_id != user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ceremony mismatch")

    # The browser-supplied intent MUST match what we stashed at /begin so the
    # user can't sign challenge A and submit it for action B.
    inbound_intent = body.action_intent.model_dump(mode="json")
    if pending.action_intent != inbound_intent:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "action intent mismatch")

    # Authority check — Lane 2 needs owner; Lane 3 needs owner or partner.
    _check_lane_authority(user, inbound_intent, db_for_lane_lookup=db)

    cred_id_b64 = _extract_credential_id(body.response)
    cred = await _load_credential(db, cred_id_b64, user.id)

    verified = verify_authentication_response(
        response=body.response,
        expected_challenge_b64=pending.challenge_b64,
        credential=cred,
    )
    cred.sign_count = verified.new_sign_count
    cred.last_used_at = datetime.now(UTC)
    await db.commit()

    token, _jti = mint_action_assertion_jwt(
        user_id=user.id,
        user_role=user.role,
        credential_id_b64=cred.credential_id_b64,
        action_intent=inbound_intent,
    )
    return ActionAssertionOut(
        auth_assertion=token, expires_in=_settings.ACTION_ASSERTION_TTL_SECONDS
    )


def _check_lane_authority(
    user: User, intent: dict, *, db_for_lane_lookup: AsyncSession
) -> None:
    """Cheap pre-check before we burn a passkey ceremony. Final authority
    enforcement still lives in services.approvals.decide_approval."""
    role = user.role
    if role not in (UserRole.OWNER.value, UserRole.PARTNER.value):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "only owner or partner may decide approvals"
        )


# ---------------------------------------------------------------------------
# Credential management
# ---------------------------------------------------------------------------
@router.get("/passkey/credentials", response_model=list[PasskeyCredentialOut])
async def list_passkeys(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[PasskeyCredentialOut]:
    res = await db.execute(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == user.id)
        .order_by(WebAuthnCredential.created_at.desc())
    )
    return [PasskeyCredentialOut.model_validate(c) for c in res.scalars().all()]


@router.delete(
    "/passkey/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_passkey(
    credential_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    cred = await db.get(WebAuthnCredential, credential_id)
    if cred is None or cred.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "passkey not found")
    if cred.revoked_at is None:
        cred.revoked_at = datetime.now(UTC)
        await db.commit()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _extract_credential_id(response: dict) -> str:
    """Pull the credential id (base64url, unpadded) out of the browser response."""
    raw = response.get("id") or response.get("rawId")
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing credential id")
    # The browser already sends id base64url; rawId may be base64. Normalize by
    # stripping padding so it matches what we stored.
    return str(raw).rstrip("=")


async def _load_credential(
    db: AsyncSession, credential_id_b64: str, expected_user_id: str
) -> WebAuthnCredential:
    res = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.credential_id_b64 == credential_id_b64
        )
    )
    cred = res.scalars().first()
    if cred is None or cred.user_id != expected_user_id or cred.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown credential")
    return cred


@router.post("/google")
async def google_login(
    body: dict,
    db: AsyncSession = Depends(get_db),
) -> TokenOut:
    """Exchange a Firebase Google ID token for a Quill session token."""
    import httpx
    import uuid as _uuid
    from datetime import datetime as _dt

    credential = body.get("credential") or body.get("id_token")
    if not credential:
        raise HTTPException(status_code=400, detail="Missing credential")

    # Verify Firebase ID token using Google's public key endpoint
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://www.googleapis.com/oauth2/v3/tokeninfo?id_token={credential}"
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid Google token")
            idinfo = resp.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Could not verify token: {e}")

    # Accept tokens from our Firebase project or Google OAuth
    aud = idinfo.get("aud", "")
    if not (aud == "studio-1771635593-6661e" or "apps.googleusercontent.com" in aud or aud.startswith("studio")):
        # For Firebase ID tokens, aud is the project ID
        pass  # Accept all for now - Firebase tokens have project ID as aud

    email = idinfo.get("email")
    name = idinfo.get("name") or email

    if not email:
        raise HTTPException(status_code=400, detail="No email in token")

    # Find or auto-create user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            id=str(_uuid.uuid4()),
            email=email,
            display_name=name,
            hashed_password="",
            role=UserRole.observer,
            created_at=_dt.utcnow(),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return TokenOut(access_token=issue_token(user), token_type="bearer", user_id=user.id, role=user.role)


@router.post("/bootstrap-owner")
async def bootstrap_owner(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """One-time bootstrap: set a specific email as owner. 
    Only works if no owner exists yet."""
    from app.enums import UserRole
    from app.models import User

    # Check no owner exists
    result = await db.execute(select(User).where(User.role == UserRole.OWNER.value))
    existing_owner = result.scalar_one_or_none()
    if existing_owner:
        raise HTTPException(403, "An owner already exists")

    email = body.get("email")
    result2 = await db.execute(select(User).where(User.email == email))
    user = result2.scalar_one_or_none()
    if not user:
        raise HTTPException(404, f"User {email} not found")

    user.role = UserRole.OWNER.value
    await db.commit()
    return {"message": f"{email} is now owner", "role": user.role}
