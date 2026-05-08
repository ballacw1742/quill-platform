"""WebAuthn / passkey + action-assertion helpers.

This module is the single source of truth for Sprint 2.2 passkey ceremonies:
    * generate / verify registration (attestation)
    * generate / verify authentication (assertion)
    * mint / verify the short-lived `auth_assertion` JWT used to gate
      approval decisions

The lower-level signing and password helpers continue to live in
``app.security`` (kept stable for Sprint 1 callers + tests).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from jose import JWTError, jwt
from webauthn import (
    generate_authentication_options as _gen_auth_opts,
)
from webauthn import (
    generate_registration_options as _gen_reg_opts,
)
from webauthn import (
    options_to_json,
)
from webauthn import (
    verify_authentication_response as _verify_auth_resp,
)
from webauthn import (
    verify_registration_response as _verify_reg_resp,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialType,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import get_settings
from app.models import User, WebAuthnCredential

_settings = get_settings()

# Algorithm used for both the user session JWT and the action assertion.
_JWT_ALGO = "HS256"

# Action assertion scope — claim that the bearer earned a one-shot decision token.
ACTION_ASSERTION_SCOPE = "approval-decision"


# ---------------------------------------------------------------------------
# base64url helpers
# ---------------------------------------------------------------------------
def b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


# ---------------------------------------------------------------------------
# Registration ceremony
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class RegistrationOptionsResult:
    options_json: str
    challenge_b64: str  # the raw challenge we issued, stash + verify later


def generate_registration_options(
    user: User,
    *,
    existing_credentials: list[WebAuthnCredential],
    attachment: str | None = None,
) -> RegistrationOptionsResult:
    """Build PublicKeyCredentialCreationOptions for the browser ceremony.

    `attachment` is an optional UI hint:
        * "platform"        — prefer Touch ID / Face ID / iCloud Keychain
        * "cross-platform"  — suggest a hardware key (YubiKey)
        * None              — no preference
    """

    selection_attachment: AuthenticatorAttachment | None = None
    if attachment == "platform":
        selection_attachment = AuthenticatorAttachment.PLATFORM
    elif attachment == "cross-platform":
        selection_attachment = AuthenticatorAttachment.CROSS_PLATFORM

    selection = AuthenticatorSelectionCriteria(
        authenticator_attachment=selection_attachment,
        resident_key=ResidentKeyRequirement.PREFERRED,
        user_verification=UserVerificationRequirement.REQUIRED,
    )

    exclude = [
        PublicKeyCredentialDescriptor(
            id=b64url_decode(c.credential_id_b64),
            type=PublicKeyCredentialType.PUBLIC_KEY,
        )
        for c in existing_credentials
        if c.revoked_at is None
    ]

    opts = _gen_reg_opts(
        rp_id=_settings.WEBAUTHN_RP_ID,
        rp_name=_settings.WEBAUTHN_RP_NAME,
        user_id=user.id.encode("utf-8"),
        user_name=user.email,
        user_display_name=user.display_name or user.email,
        authenticator_selection=selection,
        exclude_credentials=exclude,
        supported_pub_key_algs=[
            COSEAlgorithmIdentifier.ECDSA_SHA_256,
            COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
            COSEAlgorithmIdentifier.EDDSA,
        ],
    )
    return RegistrationOptionsResult(
        options_json=options_to_json(opts),
        challenge_b64=b64url_encode(opts.challenge),
    )


@dataclass(slots=True)
class VerifiedRegistration:
    credential_id_b64: str
    public_key_b64: str
    sign_count: int
    transports: str | None
    attachment: str | None
    aaguid: str | None
    backup_eligible: bool
    backup_state: bool


def verify_registration_response(
    *,
    response: dict[str, Any],
    expected_challenge_b64: str,
) -> VerifiedRegistration:
    try:
        verification = _verify_reg_resp(
            credential=response,
            expected_challenge=b64url_decode(expected_challenge_b64),
            expected_rp_id=_settings.WEBAUTHN_RP_ID,
            expected_origin=_settings.webauthn_origins,
            require_user_verification=True,
        )
    except Exception as exc:  # pragma: no cover - library raises a few subclasses
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"passkey registration failed: {exc}"
        ) from exc

    transports_csv: str | None = None
    attachment: str | None = None
    if isinstance(response, dict):
        inner = response.get("response") if isinstance(response.get("response"), dict) else None
        if inner:
            t = inner.get("transports")
            if isinstance(t, list) and t:
                transports_csv = ",".join(str(x) for x in t)
        # The browser's PublicKeyCredential exposes `authenticatorAttachment`
        # as "platform" or "cross-platform".
        att = response.get("authenticatorAttachment")
        if isinstance(att, str):
            attachment = att

    return VerifiedRegistration(
        credential_id_b64=b64url_encode(verification.credential_id),
        public_key_b64=base64.b64encode(verification.credential_public_key).decode("ascii"),
        sign_count=int(verification.sign_count or 0),
        transports=transports_csv,
        attachment=attachment,
        aaguid=str(verification.aaguid) if getattr(verification, "aaguid", None) else None,
        backup_eligible=bool(getattr(verification, "credential_backed_up", False)),
        backup_state=bool(getattr(verification, "credential_backed_up", False)),
    )


# ---------------------------------------------------------------------------
# Authentication ceremony
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class AuthenticationOptionsResult:
    options_json: str
    challenge_b64: str
    allowed_credential_ids_b64: list[str]


def generate_authentication_options(
    *,
    credentials: list[WebAuthnCredential],
) -> AuthenticationOptionsResult:
    """Build PublicKeyCredentialRequestOptions for sign-in or re-auth."""
    allow = [
        PublicKeyCredentialDescriptor(
            id=b64url_decode(c.credential_id_b64),
            type=PublicKeyCredentialType.PUBLIC_KEY,
            transports=_parse_transports(c.transports),
        )
        for c in credentials
        if c.revoked_at is None
    ]
    opts = _gen_auth_opts(
        rp_id=_settings.WEBAUTHN_RP_ID,
        allow_credentials=allow,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return AuthenticationOptionsResult(
        options_json=options_to_json(opts),
        challenge_b64=b64url_encode(opts.challenge),
        allowed_credential_ids_b64=[c.credential_id_b64 for c in credentials if c.revoked_at is None],
    )


def _parse_transports(csv: str | None):
    if not csv:
        return None
    from webauthn.helpers.structs import AuthenticatorTransport

    valid = {t.value for t in AuthenticatorTransport}
    out: list[AuthenticatorTransport] = []
    for raw in csv.split(","):
        raw = raw.strip()
        if raw in valid:
            out.append(AuthenticatorTransport(raw))
    return out or None


@dataclass(slots=True)
class VerifiedAssertion:
    credential_id_b64: str
    new_sign_count: int


def verify_authentication_response(
    *,
    response: dict[str, Any],
    expected_challenge_b64: str,
    credential: WebAuthnCredential,
) -> VerifiedAssertion:
    try:
        verification = _verify_auth_resp(
            credential=response,
            expected_challenge=b64url_decode(expected_challenge_b64),
            expected_rp_id=_settings.WEBAUTHN_RP_ID,
            expected_origin=_settings.webauthn_origins,
            credential_public_key=base64.b64decode(credential.public_key_b64),
            credential_current_sign_count=credential.sign_count,
            require_user_verification=True,
        )
    except Exception as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"passkey verification failed: {exc}"
        ) from exc

    return VerifiedAssertion(
        credential_id_b64=credential.credential_id_b64,
        new_sign_count=int(verification.new_sign_count),
    )


# ---------------------------------------------------------------------------
# Action assertion JWT — short-lived, scoped, intent-bound.
# ---------------------------------------------------------------------------
def _intent_hash(intent: dict[str, Any]) -> str:
    """Deterministic hash of an action_intent dict; survives key reordering."""
    canonical = json.dumps(intent, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def mint_action_assertion_jwt(
    *,
    user_id: str,
    user_role: str,
    credential_id_b64: str,
    action_intent: dict[str, Any],
    ttl_seconds: int | None = None,
) -> tuple[str, str]:
    """Mint a one-shot JWT for an approval decision. Returns (token, jti)."""
    ttl = ttl_seconds or _settings.ACTION_ASSERTION_TTL_SECONDS
    now = datetime.now(UTC)
    jti = secrets.token_urlsafe(16)
    claims: dict[str, Any] = {
        "sub": user_id,
        "role": user_role,
        "scope": ACTION_ASSERTION_SCOPE,
        "cred": credential_id_b64,
        "intent_hash": _intent_hash(action_intent),
        "intent": action_intent,  # echoed for diagnostics; verification uses hash
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "jti": jti,
    }
    token = jwt.encode(claims, _settings.ACTION_ASSERTION_SECRET, algorithm=_JWT_ALGO)
    return token, jti


def verify_action_assertion_jwt(
    *,
    token: str,
    expected_intent: dict[str, Any],
    expected_user_id: str | None = None,
) -> dict[str, Any]:
    """Verify a minted action assertion. Raises 401 on any failure.

    Replay protection is provided by:
        * the 60s expiry on `exp`
        * the `intent_hash` claim, which must match the inbound request body
        * the one-shot `jti` (callers MUST add to a used-set after success)
    """
    try:
        claims = jwt.decode(token, _settings.ACTION_ASSERTION_SECRET, algorithms=[_JWT_ALGO])
    except JWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"action assertion invalid: {exc}"
        ) from exc

    if claims.get("scope") != ACTION_ASSERTION_SCOPE:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "action assertion: wrong scope")
    if expected_user_id and claims.get("sub") != expected_user_id:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "action assertion: user mismatch"
        )
    if claims.get("intent_hash") != _intent_hash(expected_intent):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "action assertion: intent mismatch"
        )
    return claims


# ---------------------------------------------------------------------------
# In-memory replay-protection store for action assertion JTIs.
# Suitable for single-process dev; swap for Redis in prod.
# ---------------------------------------------------------------------------
class _UsedJtiStore:
    def __init__(self) -> None:
        self._used: dict[str, float] = {}

    def consume(self, jti: str, exp_ts: float) -> bool:
        """Mark a jti as used. Returns True if this is the FIRST use."""
        self._gc()
        if jti in self._used:
            return False
        self._used[jti] = exp_ts
        return True

    def _gc(self) -> None:
        now = datetime.now(UTC).timestamp()
        for k, exp in list(self._used.items()):
            if exp < now:
                del self._used[k]


used_action_jtis = _UsedJtiStore()


# ---------------------------------------------------------------------------
# In-memory challenge store for ongoing ceremonies.
# Keyed by an opaque `ceremony_id` issued to the browser.
# ---------------------------------------------------------------------------
@dataclass
class _PendingCeremony:
    challenge_b64: str
    user_id: str | None
    kind: str  # "register" | "login" | "action"
    action_intent: dict[str, Any] | None
    expires_at: float


class _ChallengeStore:
    def __init__(self) -> None:
        self._items: dict[str, _PendingCeremony] = {}

    def put(
        self,
        *,
        challenge_b64: str,
        user_id: str | None,
        kind: str,
        action_intent: dict[str, Any] | None = None,
        ttl_seconds: int = 300,
    ) -> str:
        cid = secrets.token_urlsafe(24)
        self._items[cid] = _PendingCeremony(
            challenge_b64=challenge_b64,
            user_id=user_id,
            kind=kind,
            action_intent=action_intent,
            expires_at=datetime.now(UTC).timestamp() + ttl_seconds,
        )
        self._gc()
        return cid

    def take(self, cid: str) -> _PendingCeremony:
        self._gc()
        item = self._items.pop(cid, None)
        if item is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "ceremony expired or unknown"
            )
        return item

    def _gc(self) -> None:
        now = datetime.now(UTC).timestamp()
        for k, v in list(self._items.items()):
            if v.expires_at < now:
                del self._items[k]


challenge_store = _ChallengeStore()


__all__ = [
    "ACTION_ASSERTION_SCOPE",
    "AuthenticationOptionsResult",
    "RegistrationOptionsResult",
    "VerifiedAssertion",
    "VerifiedRegistration",
    "b64url_decode",
    "b64url_encode",
    "challenge_store",
    "generate_authentication_options",
    "generate_registration_options",
    "mint_action_assertion_jwt",
    "used_action_jtis",
    "verify_action_assertion_jwt",
    "verify_authentication_response",
    "verify_registration_response",
]
