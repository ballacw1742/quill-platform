"""Per-tenant secrets (SECRETS.md) — provider abstraction, round-trips,
rotation, list-never-values, name validation, decrypt errors, RLS (pg)."""

import os

import pytest

from app import secrets as secrets_mod
from app.config import get_settings


@pytest.fixture(autouse=True)
def _reset_backend():
    secrets_mod.set_kms_client_factory(None)
    get_settings.cache_clear()
    yield
    secrets_mod.set_kms_client_factory(None)
    get_settings.cache_clear()


# ---- mocked KMS: a reversible wrap/unwrap that never touches the network ----


class _MockKmsResp:
    def __init__(self, blob):
        self.ciphertext = blob
        self.plaintext = blob


class MockKmsClient:
    """Round-trips wrap/unwrap by XOR-ing with a fixed pad — proves the
    envelope path end to end without a real KMS. Not cryptographically real;
    it only needs to be a reversible transform over the DEK."""

    PAD = b"\xa5" * 32
    calls = {"encrypt": 0, "decrypt": 0}

    def _xor(self, data: bytes) -> bytes:
        pad = (self.PAD * (len(data) // len(self.PAD) + 1))[: len(data)]
        return bytes(a ^ b for a, b in zip(data, pad))

    def encrypt(self, request):
        MockKmsClient.calls["encrypt"] += 1
        return _MockKmsResp(b"WRAP:" + self._xor(request["plaintext"]))

    def decrypt(self, request):
        MockKmsClient.calls["decrypt"] += 1
        assert request["ciphertext"].startswith(b"WRAP:")
        return _MockKmsResp(self._xor(request["ciphertext"][len(b"WRAP:") :]))


# ---- plaintext-dev backend (default) ----


async def test_plaintext_roundtrip():
    t = "smoke-secrets-plain"
    await secrets_mod.set_secret(t, "telegram_bot_token", "12345:ABCDEF")
    assert await secrets_mod.get_secret(t, "telegram_bot_token") == "12345:ABCDEF"


async def test_get_missing_returns_none():
    assert await secrets_mod.get_secret("smoke-secrets-none", "nope") is None


async def test_overwrite_stamps_rotated_at():
    t = "smoke-secrets-rot"
    await secrets_mod.set_secret(t, "api_key", "v1")
    lst = await secrets_mod.list_secrets(t)
    assert lst[0]["rotated_at"] is None
    await secrets_mod.set_secret(t, "api_key", "v2")
    assert await secrets_mod.get_secret(t, "api_key") == "v2"
    lst2 = await secrets_mod.list_secrets(t)
    assert lst2[0]["rotated_at"] is not None


async def test_list_never_returns_values():
    t = "smoke-secrets-list"
    await secrets_mod.set_secret(t, "a", "secret-a")
    await secrets_mod.set_secret(t, "b", "secret-b")
    lst = await secrets_mod.list_secrets(t)
    assert {x["name"] for x in lst} == {"a", "b"}
    for x in lst:
        assert "value" not in x and "ciphertext" not in x
        assert set(x.keys()) == {"name", "backend", "created_at", "rotated_at"}


async def test_delete_secret():
    t = "smoke-secrets-del"
    await secrets_mod.set_secret(t, "k", "v")
    assert await secrets_mod.delete_secret(t, "k") is True
    assert await secrets_mod.get_secret(t, "k") is None
    assert await secrets_mod.delete_secret(t, "k") is False


async def test_name_validation():
    with pytest.raises(secrets_mod.SecretNameError):
        await secrets_mod.set_secret("smoke-secrets-bad", "Bad Name!", "v")
    with pytest.raises(secrets_mod.SecretNameError):
        await secrets_mod.get_secret("smoke-secrets-bad", "x" * 200)


async def test_empty_value_rejected():
    with pytest.raises(secrets_mod.SecretError):
        await secrets_mod.set_secret("smoke-secrets-empty", "k", "")


# ---- kms backend (mocked) ----


async def test_kms_roundtrip(monkeypatch):
    monkeypatch.setenv("SECRETS_BACKEND", "kms")
    monkeypatch.setenv("SECRETS_KMS_KEY", "projects/p/locations/l/keyRings/r/cryptoKeys/k")
    get_settings.cache_clear()
    secrets_mod.set_kms_client_factory(lambda: MockKmsClient())
    t = "smoke-secrets-kms"
    await secrets_mod.set_secret(t, "third_party_key", "sk-super-secret")
    assert await secrets_mod.get_secret(t, "third_party_key") == "sk-super-secret"


async def test_kms_row_shape_is_encrypted(monkeypatch):
    import sqlalchemy as sa
    from app.db import tenant_session
    from app.models import TenantSecret

    monkeypatch.setenv("SECRETS_BACKEND", "kms")
    monkeypatch.setenv("SECRETS_KMS_KEY", "projects/p/locations/l/keyRings/r/cryptoKeys/k")
    get_settings.cache_clear()
    secrets_mod.set_kms_client_factory(lambda: MockKmsClient())
    t = "smoke-secrets-kms-shape"
    plaintext = "do-not-store-me-raw"
    await secrets_mod.set_secret(t, "tok", plaintext)
    async with tenant_session(t) as db:
        row = (
            await db.execute(
                sa.select(TenantSecret).where(
                    TenantSecret.tenant_id == t, TenantSecret.name == "tok"
                )
            )
        ).scalar_one()
    assert row.backend == "kms"
    assert row.kms_key_ref
    assert row.dek_wrapped is not None and row.nonce is not None
    # the raw plaintext must NOT appear in the stored ciphertext
    assert plaintext.encode() not in bytes(row.ciphertext)


async def test_kms_requires_key(monkeypatch):
    monkeypatch.setenv("SECRETS_BACKEND", "kms")
    monkeypatch.setenv("SECRETS_KMS_KEY", "")
    get_settings.cache_clear()
    secrets_mod.set_kms_client_factory(lambda: MockKmsClient())
    with pytest.raises(secrets_mod.SecretError):
        await secrets_mod.set_secret("smoke-secrets-nokey", "k", "v")


async def test_kms_tampered_ciphertext_raises_decrypt_error(monkeypatch):
    import sqlalchemy as sa
    from app.db import tenant_session
    from app.models import TenantSecret

    monkeypatch.setenv("SECRETS_BACKEND", "kms")
    monkeypatch.setenv("SECRETS_KMS_KEY", "projects/p/locations/l/keyRings/r/cryptoKeys/k")
    get_settings.cache_clear()
    secrets_mod.set_kms_client_factory(lambda: MockKmsClient())
    t = "smoke-secrets-tamper"
    await secrets_mod.set_secret(t, "tok", "value")
    # flip a byte in the ciphertext → AES-GCM auth must fail
    async with tenant_session(t) as db:
        row = (
            await db.execute(
                sa.select(TenantSecret).where(
                    TenantSecret.tenant_id == t, TenantSecret.name == "tok"
                )
            )
        ).scalar_one()
        tampered = bytearray(bytes(row.ciphertext))
        tampered[0] ^= 0xFF
        await db.execute(
            sa.update(TenantSecret)
            .where(TenantSecret.tenant_id == t, TenantSecret.name == "tok")
            .values(ciphertext=bytes(tampered))
        )
    with pytest.raises(secrets_mod.SecretDecryptError):
        await secrets_mod.get_secret(t, "tok")


async def test_unknown_backend_read_raises(monkeypatch):
    import sqlalchemy as sa
    from app.db import tenant_session
    from app.models import TenantSecret

    t = "smoke-secrets-unknown"
    await secrets_mod.set_secret(t, "k", "v")  # plaintext-dev
    async with tenant_session(t) as db:
        await db.execute(
            sa.update(TenantSecret)
            .where(TenantSecret.tenant_id == t, TenantSecret.name == "k")
            .values(backend="martian")
        )
    with pytest.raises(secrets_mod.SecretDecryptError):
        await secrets_mod.get_secret(t, "k")


async def test_plaintext_row_readable_after_backend_flip(monkeypatch):
    """A plaintext-dev row stays readable after SECRETS_BACKEND=kms (the row
    records its own backend — SECRETS.md §2)."""
    t = "smoke-secrets-migrate"
    await secrets_mod.set_secret(t, "old", "legacy-value")  # written as plaintext-dev
    monkeypatch.setenv("SECRETS_BACKEND", "kms")
    monkeypatch.setenv("SECRETS_KMS_KEY", "projects/p/locations/l/keyRings/r/cryptoKeys/k")
    get_settings.cache_clear()
    secrets_mod.set_kms_client_factory(lambda: MockKmsClient())
    assert await secrets_mod.get_secret(t, "old") == "legacy-value"  # still plaintext path


# ---- RLS (pg-gated) ----

PG_DSN = os.environ.get("AGENTCLOUD_TEST_PG_DSN")


@pytest.mark.skipif(not PG_DSN, reason="AGENTCLOUD_TEST_PG_DSN not set (needs Postgres)")
async def test_secrets_rls_cross_tenant_isolation():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db import normalize_dsn
    from app.migrations import run_migrations

    engine = create_async_engine(normalize_dsn(PG_DSN))
    await run_migrations(engine)
    a, b = "smoke-secrets-rls-a", "smoke-secrets-rls-b"
    try:
        # seed a secret for tenant A under A's GUC
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a}
            )
            await conn.execute(
                text(
                    "INSERT INTO agentcloud_tenant_secrets "
                    "(tenant_id, name, backend, ciphertext) "
                    "VALUES (:t, 'tok', 'plaintext-dev', :c)"
                ),
                {"t": a, "c": b"secret-bytes"},
            )
        # tenant B's GUC must NOT see A's secret row
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": b}
            )
            n = (
                await conn.execute(
                    text("SELECT count(*) FROM agentcloud_tenant_secrets")
                )
            ).scalar_one()
            assert n == 0
        # A's own GUC sees exactly its row
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a}
            )
            n = (
                await conn.execute(
                    text("SELECT count(*) FROM agentcloud_tenant_secrets")
                )
            ).scalar_one()
            assert n == 1
        # forged INSERT under B's GUC for A's tenant_id must be blocked by WITH CHECK
        import asyncpg  # noqa: F401

        with pytest.raises(Exception):
            async with engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"), {"t": b}
                )
                await conn.execute(
                    text(
                        "INSERT INTO agentcloud_tenant_secrets "
                        "(tenant_id, name, backend, ciphertext) "
                        "VALUES (:t, 'forged', 'plaintext-dev', :c)"
                    ),
                    {"t": a, "c": b"x"},
                )
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.admin', 'on', true)"))
            await conn.execute(
                text("DELETE FROM agentcloud_tenant_secrets WHERE tenant_id LIKE 'smoke-secrets-rls-%'")
            )
        await engine.dispose()
