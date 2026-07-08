"""Per-tenant secrets — provider abstraction (contract: SECRETS.md).

Two backends, config-gated by SECRETS_BACKEND exactly like MODEL_PROVIDER /
EVENT_BUS:

  - "plaintext-dev" (default): ciphertext holds the raw UTF-8 value;
    dek_wrapped/nonce/kms_key_ref are NULL. Dev/tests only — the name is
    deliberately alarming in any prod-shaped review. Waives the
    "a DB dump discloses nothing" property on purpose.

  - "kms": AES-256-GCM envelope encryption. A fresh 256-bit DEK per value
    encrypts the plaintext (fresh 96-bit nonce, AAD binds ciphertext to
    tenant+name); the DEK is wrapped by Cloud KMS. The KEK never touches the
    DB or disk. The google-cloud-kms client is imported lazily and is
    injectable for tests (a mocked KMS round-trips wrap/unwrap w/o network).

All access goes through this module (SECRETS.md §4). Every read/write runs
inside tenant_session(tenant_id) so RLS is the second belt under the
app-layer tenant filter. KMS network calls happen OUTSIDE the DB tx (same
no-conn-during-network discipline as model/embedding calls).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite

from app.config import get_settings
from app.db import tenant_session
from app.models import TenantSecret

log = logging.getLogger("agentcloud.secrets")

NAME_RE = re.compile(r"^[a-z0-9_.-]{1,128}$")

# Injectable KMS client factory for tests (mocked KMS). Prod uses the real
# google-cloud-kms client, imported lazily inside _get_kms_client().
_kms_client_factory: Callable[[], Any] | None = None


class SecretError(Exception):
    """Base class for secrets errors."""


class SecretNameError(SecretError):
    """Invalid secret name."""


class SecretDecryptError(SecretError):
    """A stored row could not be decrypted (bad KMS perms, tampered
    ciphertext/AAD mismatch, unknown backend). Must be surfaced as a clean
    tool error, never a stack trace with key material."""


def set_kms_client_factory(fn: Callable[[], Any] | None) -> None:
    """Test hook: inject a mocked KMS client factory (or reset to None)."""
    global _kms_client_factory
    _kms_client_factory = fn


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise SecretNameError(
            "secret name must be 1–128 chars of [a-z0-9_.-]"
        )
    return name


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aad(tenant_id: str, name: str) -> bytes:
    return f"agentcloud:{tenant_id}:{name}".encode()


def _get_kms_client():
    if _kms_client_factory is not None:
        return _kms_client_factory()
    from google.cloud import kms  # noqa: PLC0415  # pragma: no cover

    return kms.KeyManagementServiceClient()  # pragma: no cover


# --- backend: kms (envelope encryption) ---------------------------------


def _kms_wrap(kms_key: str, dek: bytes) -> bytes:
    client = _get_kms_client()
    resp = client.encrypt(request={"name": kms_key, "plaintext": dek})
    return resp.ciphertext


def _kms_unwrap(kms_key_ref: str, dek_wrapped: bytes) -> bytes:
    client = _get_kms_client()
    resp = client.decrypt(request={"name": kms_key_ref, "ciphertext": dek_wrapped})
    return resp.plaintext


def _encrypt_kms(tenant_id: str, name: str, value: str) -> dict[str, Any]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: PLC0415

    s = get_settings()
    kms_key = s.SECRETS_KMS_KEY
    if not kms_key:
        raise SecretError("SECRETS_BACKEND=kms requires SECRETS_KMS_KEY")
    dek = os.urandom(32)
    nonce = os.urandom(12)
    aesgcm = AESGCM(dek)
    ciphertext = aesgcm.encrypt(nonce, value.encode(), _aad(tenant_id, name))
    dek_wrapped = _kms_wrap(kms_key, dek)
    del dek  # drop plaintext DEK immediately
    return {
        "backend": "kms",
        "kms_key_ref": kms_key,
        "dek_wrapped": dek_wrapped,
        "nonce": nonce,
        "ciphertext": ciphertext,
    }


def _decrypt_kms(row: TenantSecret) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: PLC0415
    from cryptography.exceptions import InvalidTag  # noqa: PLC0415

    try:
        dek = _kms_unwrap(row.kms_key_ref, bytes(row.dek_wrapped))
        aesgcm = AESGCM(dek)
        plaintext = aesgcm.decrypt(
            bytes(row.nonce), bytes(row.ciphertext), _aad(row.tenant_id, row.name)
        )
        return plaintext.decode()
    except InvalidTag as exc:
        raise SecretDecryptError(
            f"secret {row.name!r} failed AES-GCM auth (tampered ciphertext/AAD)"
        ) from exc
    except SecretError:
        raise
    except Exception as exc:  # noqa: BLE001 — never leak KMS internals/material
        raise SecretDecryptError(
            f"secret {row.name!r} could not be decrypted via KMS"
        ) from exc


# --- write / read / delete / list ---------------------------------------


def _encrypt(tenant_id: str, name: str, value: str) -> dict[str, Any]:
    backend = get_settings().SECRETS_BACKEND
    if backend == "plaintext-dev":
        return {
            "backend": "plaintext-dev",
            "kms_key_ref": None,
            "dek_wrapped": None,
            "nonce": None,
            "ciphertext": value.encode(),
        }
    if backend == "kms":
        return _encrypt_kms(tenant_id, name, value)
    raise SecretError(f"unknown SECRETS_BACKEND {backend!r} (plaintext-dev|kms)")


def _decrypt(row: TenantSecret) -> str:
    if row.backend == "plaintext-dev":
        return bytes(row.ciphertext).decode()
    if row.backend == "kms":
        return _decrypt_kms(row)
    raise SecretDecryptError(f"unknown secret backend {row.backend!r}")


def _upsert(model_cls, values: dict, dialect: str):
    set_ = {k: values[k] for k in values if k not in ("tenant_id", "name")}
    set_["rotated_at"] = values["created_at"]  # overwrite stamps rotated_at
    if dialect == "postgresql":
        stmt = postgresql.insert(model_cls).values(**values)
        return stmt.on_conflict_do_update(
            index_elements=["tenant_id", "name"], set_=set_
        )
    stmt = sqlite.insert(model_cls).values(**values)
    return stmt.on_conflict_do_update(index_elements=["tenant_id", "name"], set_=set_)


async def set_secret(tenant_id: str, name: str, value: str) -> None:
    """Upsert one secret. On overwrite of an existing name, rotated_at is
    stamped (SECRETS.md §2). Encryption happens OUTSIDE the DB tx (KMS is a
    network call); only the row write is inside tenant_session."""
    _validate_name(name)
    if not isinstance(value, str) or value == "":
        raise SecretError("secret value must be a non-empty string")
    enc = _encrypt(tenant_id, name, value)  # network (KMS) happens here, no DB conn
    now = _utcnow()
    async with tenant_session(tenant_id) as db:
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
        await db.execute(
            _upsert(
                TenantSecret,
                {
                    "tenant_id": tenant_id,
                    "name": name,
                    "created_at": now,
                    **enc,
                },
                dialect,
            )
        )


async def get_secret(tenant_id: str, name: str) -> str | None:
    """Return the decrypted plaintext (SECRETS.md §4) or None if not set.

    The row is fetched inside tenant_session (RLS second belt); the KMS
    decrypt happens after the tx closes (no DB conn held during network).
    """
    _validate_name(name)
    async with tenant_session(tenant_id) as db:
        row = (
            await db.execute(
                sa.select(TenantSecret).where(
                    TenantSecret.tenant_id == tenant_id,
                    TenantSecret.name == name,
                )
            )
        ).scalar_one_or_none()
    if row is None:
        return None
    return _decrypt(row)


async def delete_secret(tenant_id: str, name: str) -> bool:
    """Delete a secret. Returns True if a row was removed."""
    _validate_name(name)
    async with tenant_session(tenant_id) as db:
        res = await db.execute(
            sa.delete(TenantSecret).where(
                TenantSecret.tenant_id == tenant_id,
                TenantSecret.name == name,
            )
        )
        return res.rowcount > 0


async def list_secrets(tenant_id: str) -> list[dict[str, Any]]:
    """List secret metadata — NEVER values (SECRETS.md §4)."""
    async with tenant_session(tenant_id) as db:
        rows = (
            (
                await db.execute(
                    sa.select(TenantSecret)
                    .where(TenantSecret.tenant_id == tenant_id)
                    .order_by(TenantSecret.name)
                )
            )
            .scalars()
            .all()
        )
    return [
        {
            "name": r.name,
            "backend": r.backend,
            "created_at": r.created_at,
            "rotated_at": r.rotated_at,
        }
        for r in rows
    ]
