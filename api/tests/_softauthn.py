"""Software WebAuthn authenticator for tests.

Produces real attestation + assertion responses that the `webauthn` server
library can verify end-to-end. ECDSA P-256 (ES256, COSE alg = -7).

This is intentionally minimal: format=\"none\" attestation, no transports
quirks, single counter. Good enough to exercise the full verification path.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (  # noqa: F401
    decode_dss_signature,
    encode_dss_signature,
)


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


# ---------------------------------------------------------------------------
# COSE encoding for an EC2 P-256 key.
# COSE labels: 1=kty, 3=alg, -1=crv, -2=x, -3=y
# ---------------------------------------------------------------------------
def _cose_ec_pub_key(public_numbers: ec.EllipticCurvePublicNumbers) -> bytes:
    x = public_numbers.x.to_bytes(32, "big")
    y = public_numbers.y.to_bytes(32, "big")
    cose = {1: 2, 3: -7, -1: 1, -2: x, -3: y}
    return cbor2.dumps(cose)


# ---------------------------------------------------------------------------
# Authenticator data structure (per spec):
#   rpIdHash (32) | flags (1) | signCount (4) | attestedCredentialData? | extensions?
# Flags: UP=0x01 UV=0x04 BE=0x08 BS=0x10 AT=0x40 ED=0x80
# ---------------------------------------------------------------------------
def _build_auth_data(
    *,
    rp_id: str,
    sign_count: int,
    aaguid: bytes = b"\x00" * 16,
    credential_id: bytes | None = None,
    cose_pub_key: bytes | None = None,
    user_present: bool = True,
    user_verified: bool = True,
) -> bytes:
    rp_id_hash = hashlib.sha256(rp_id.encode()).digest()
    flags = 0
    if user_present:
        flags |= 0x01
    if user_verified:
        flags |= 0x04
    if credential_id is not None:
        flags |= 0x40  # AT
    sc = sign_count.to_bytes(4, "big")

    out = rp_id_hash + bytes([flags]) + sc
    if credential_id is not None:
        assert cose_pub_key is not None
        out += aaguid
        out += len(credential_id).to_bytes(2, "big")
        out += credential_id
        out += cose_pub_key
    return out


# ---------------------------------------------------------------------------
# Software authenticator
# ---------------------------------------------------------------------------
@dataclass
class SoftAuthn:
    rp_id: str
    origin: str
    credential_id: bytes = field(default_factory=lambda: os.urandom(32))
    sign_count: int = 0
    private_key: ec.EllipticCurvePrivateKey = field(
        default_factory=lambda: ec.generate_private_key(ec.SECP256R1())
    )

    @property
    def credential_id_b64url(self) -> str:
        return b64url(self.credential_id)

    @property
    def cose_pub_key(self) -> bytes:
        return _cose_ec_pub_key(self.private_key.public_key().public_numbers())

    # ---- Registration ceremony --------------------------------------------
    def make_registration_response(self, challenge_b64url: str) -> dict[str, Any]:
        client_data = {
            "type": "webauthn.create",
            "challenge": challenge_b64url,
            "origin": self.origin,
        }
        client_data_json = json.dumps(client_data, separators=(",", ":")).encode()

        auth_data = _build_auth_data(
            rp_id=self.rp_id,
            sign_count=self.sign_count,
            credential_id=self.credential_id,
            cose_pub_key=self.cose_pub_key,
        )

        # "none" attestation: empty attStmt, fmt = "none"
        attestation_object = cbor2.dumps(
            {"fmt": "none", "attStmt": {}, "authData": auth_data}
        )

        return {
            "id": self.credential_id_b64url,
            "rawId": self.credential_id_b64url,
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "response": {
                "clientDataJSON": b64url(client_data_json),
                "attestationObject": b64url(attestation_object),
                "transports": ["internal", "hybrid"],
            },
            "clientExtensionResults": {},
        }

    # ---- Authentication ceremony ------------------------------------------
    def make_assertion_response(self, challenge_b64url: str) -> dict[str, Any]:
        self.sign_count += 1
        client_data = {
            "type": "webauthn.get",
            "challenge": challenge_b64url,
            "origin": self.origin,
        }
        client_data_json = json.dumps(client_data, separators=(",", ":")).encode()

        auth_data = _build_auth_data(
            rp_id=self.rp_id,
            sign_count=self.sign_count,
            user_present=True,
            user_verified=True,
        )

        # WebAuthn signs sha256(clientDataJSON) appended to authData.
        client_data_hash = hashlib.sha256(client_data_json).digest()
        signature = self.private_key.sign(
            auth_data + client_data_hash, ec.ECDSA(hashes.SHA256())
        )

        return {
            "id": self.credential_id_b64url,
            "rawId": self.credential_id_b64url,
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "response": {
                "clientDataJSON": b64url(client_data_json),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": None,
            },
            "clientExtensionResults": {},
        }
