"""Age on-prem KEK secrets backend (SECRETS_BACKEND=age).

All tests mock the pyrage calls — no real age keys needed. The mock
encrypt/decrypt functions perform a trivial reversible transform (XOR with
a fixed pad) that is sufficient to prove the age backend round-trips
correctly through the existing agentcloud_tenant_secrets table.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from app import secrets as secrets_mod
from app.config import get_settings


# ---------------------------------------------------------------------------
# Mock age crypto — no real age keys, no pyrage import needed at test time
# ---------------------------------------------------------------------------

_PAD = b"\xde\xad\xbe\xef" * 64  # 256 bytes; repeated as needed


def _xor_bytes(data: bytes) -> bytes:
    pad = (_PAD * (len(data) // len(_PAD) + 1))[: len(data)]
    return bytes(a ^ b for a, b in zip(data, pad))


def _mock_encrypt(plaintext: bytes, recipients: list[str]) -> bytes:
    """Simulate age encrypt: prepend a fake header so we can assert structure."""
    header = f"age-mock:{','.join(recipients)}\n".encode()
    return header + _xor_bytes(plaintext)


def _mock_decrypt(ciphertext: bytes, identity_file: str) -> bytes:
    """Simulate age decrypt: strip the header, XOR back."""
    if b"\n" not in ciphertext:
        raise ValueError("mock: malformed ciphertext (missing header)")
    _, body = ciphertext.split(b"\n", 1)
    return _xor_bytes(body)


@pytest.fixture(autouse=True)
def _reset_age_backend():
    """Reset config cache + age overrides after every test."""
    secrets_mod.set_age_crypto_override(None, None)
    get_settings.cache_clear()
    yield
    secrets_mod.set_age_crypto_override(None, None)
    get_settings.cache_clear()


@pytest.fixture()
def age_env(tmp_path, monkeypatch):
    """Set SECRETS_BACKEND=age with a mock recipient + a real (empty) identity
    file path so the path-exists guard passes."""
    identity_file = tmp_path / "key.txt"
    identity_file.write_text("# mock age identity\n")
    monkeypatch.setenv("SECRETS_BACKEND", "age")
    monkeypatch.setenv("AGE_RECIPIENT", "age1testrecipient000000000000000000000000000000000000000")
    monkeypatch.setenv("AGE_IDENTITY_FILE", str(identity_file))
    get_settings.cache_clear()
    # Install mock crypto so no real pyrage binary/library is needed
    secrets_mod.set_age_crypto_override(_mock_encrypt, _mock_decrypt)
    return {"identity_file": str(identity_file)}


# ---------------------------------------------------------------------------
# Basic round-trip
# ---------------------------------------------------------------------------


async def test_age_roundtrip(age_env):
    t = "age-smoke-roundtrip"
    await secrets_mod.set_secret(t, "api_key", "super-secret-value")
    result = await secrets_mod.get_secret(t, "api_key")
    assert result == "super-secret-value"


async def test_age_backend_tag_stored(age_env):
    """Row must be tagged backend='age' so the row-aware decrypt path works."""
    from app.db import tenant_session
    from app.models import TenantSecret
    import sqlalchemy as sa

    t = "age-smoke-tag"
    await secrets_mod.set_secret(t, "tok", "hello")
    async with tenant_session(t) as db:
        row = (
            await db.execute(
                sa.select(TenantSecret).where(
                    TenantSecret.tenant_id == t,
                    TenantSecret.name == "tok",
                )
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.backend == "age"
    # kms_key_ref reused to store the recipient public key
    assert row.kms_key_ref is not None and row.kms_key_ref.startswith("age1")
    # dek_wrapped/nonce unused by age backend
    assert row.dek_wrapped is None
    assert row.nonce is None


async def test_age_overwrite_stamps_rotated_at(age_env):
    t = "age-smoke-rotation"
    await secrets_mod.set_secret(t, "pw", "v1")
    lst = await secrets_mod.list_secrets(t)
    assert lst[0]["rotated_at"] is None

    await secrets_mod.set_secret(t, "pw", "v2")
    assert await secrets_mod.get_secret(t, "pw") == "v2"
    lst2 = await secrets_mod.list_secrets(t)
    assert lst2[0]["rotated_at"] is not None


async def test_age_list_never_reveals_values(age_env):
    t = "age-smoke-list"
    await secrets_mod.set_secret(t, "a", "secret-a")
    await secrets_mod.set_secret(t, "b", "secret-b")
    lst = await secrets_mod.list_secrets(t)
    names = {r["name"] for r in lst}
    assert names == {"a", "b"}
    for r in lst:
        assert "value" not in r
        assert "ciphertext" not in r


async def test_age_delete(age_env):
    t = "age-smoke-delete"
    await secrets_mod.set_secret(t, "gone", "bye")
    assert await secrets_mod.get_secret(t, "gone") == "bye"
    deleted = await secrets_mod.delete_secret(t, "gone")
    assert deleted is True
    assert await secrets_mod.get_secret(t, "gone") is None


async def test_age_delete_nonexistent(age_env):
    result = await secrets_mod.delete_secret("age-smoke-noop", "nonexistent")
    assert result is False


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


async def test_age_missing_recipient_raises(monkeypatch):
    """SECRETS_BACKEND=age with no AGE_RECIPIENT must raise SecretError."""
    monkeypatch.setenv("SECRETS_BACKEND", "age")
    monkeypatch.setenv("AGE_RECIPIENT", "")
    monkeypatch.setenv("AGE_IDENTITY_FILE", "/tmp/fake.txt")
    get_settings.cache_clear()
    secrets_mod.set_age_crypto_override(_mock_encrypt, _mock_decrypt)
    with pytest.raises(secrets_mod.SecretError, match="AGE_RECIPIENT"):
        await secrets_mod.set_secret("t", "k", "v")


async def test_age_missing_identity_file_raises(tmp_path, monkeypatch):
    """get_secret with a missing identity file must raise SecretDecryptError."""
    identity_file = tmp_path / "key.txt"
    identity_file.write_text("# mock\n")
    monkeypatch.setenv("SECRETS_BACKEND", "age")
    monkeypatch.setenv("AGE_RECIPIENT", "age1testrecipient000000000000000000000000000000000000000")
    monkeypatch.setenv("AGE_IDENTITY_FILE", str(identity_file))
    get_settings.cache_clear()
    secrets_mod.set_age_crypto_override(_mock_encrypt, _mock_decrypt)

    # Write the secret (file exists at write time)
    await secrets_mod.set_secret("age-nofile", "k", "v")

    # Now point at a non-existent identity file
    monkeypatch.setenv("AGE_IDENTITY_FILE", "/tmp/does-not-exist-age-key.txt")
    get_settings.cache_clear()
    with pytest.raises(secrets_mod.SecretDecryptError, match="age identity file not found"):
        await secrets_mod.get_secret("age-nofile", "k")


async def test_age_missing_identity_env_raises(age_env, monkeypatch):
    """get_secret with AGE_IDENTITY_FILE='' must raise SecretDecryptError."""
    await secrets_mod.set_secret("age-noenv", "k", "v")
    # Strip the identity file env
    monkeypatch.setenv("AGE_IDENTITY_FILE", "")
    get_settings.cache_clear()
    with pytest.raises(secrets_mod.SecretDecryptError, match="AGE_IDENTITY_FILE"):
        await secrets_mod.get_secret("age-noenv", "k")


def test_age_pyrage_not_installed_raises_import_error(monkeypatch):
    """_load_pyrage() must raise ImportError with the pip install hint when
    pyrage is absent. We simulate absence by temporarily removing any cached
    import and injecting a failing import."""
    # Reset any cached pyrage references inside secrets_mod
    secrets_mod._pyrage_encrypt_func = None
    secrets_mod._pyrage_decrypt_func = None

    original_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def _blocking_import(name, *args, **kwargs):
        if name == "pyrage":
            raise ImportError("No module named 'pyrage'")
        return original_import(name, *args, **kwargs)

    import builtins
    monkeypatch.setattr(builtins, "__import__", _blocking_import)
    with pytest.raises(ImportError, match="pip install pyrage"):
        secrets_mod._load_pyrage()


# ---------------------------------------------------------------------------
# Cross-backend row compatibility
# ---------------------------------------------------------------------------


async def test_age_row_readable_after_backend_switch(age_env, monkeypatch):
    """A row written with SECRETS_BACKEND=age must remain readable even when
    the backend env is changed to plaintext-dev — the row.backend tag governs
    the decrypt path (SECRETS.md §2)."""
    t = "age-smoke-xcompat"
    await secrets_mod.set_secret(t, "xk", "cross-backend-value")

    # Flip to plaintext-dev — new writes use plaintext, but the existing row
    # was tagged 'age' and should still decrypt via the age path.
    monkeypatch.setenv("SECRETS_BACKEND", "plaintext-dev")
    get_settings.cache_clear()
    # Keep the mock so the age decrypt path still works
    result = await secrets_mod.get_secret(t, "xk")
    assert result == "cross-backend-value"
