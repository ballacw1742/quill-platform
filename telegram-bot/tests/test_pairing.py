"""Pairing code mint/verify tests."""

from __future__ import annotations

import time

import pytest

from quill_bot.pairing import (
    InvalidPairingCode,
    mint_code,
    verify_code,
)


SECRET = "unit-test-secret"


def test_mint_and_verify_roundtrip():
    code = mint_code("charles@example.com", SECRET)
    parsed = verify_code(code, SECRET)
    assert parsed.email == "charles@example.com"
    assert parsed.raw == code


def test_verify_rejects_bad_secret():
    code = mint_code("charles@example.com", SECRET)
    with pytest.raises(InvalidPairingCode):
        verify_code(code, "different-secret")


def test_verify_rejects_malformed():
    with pytest.raises(InvalidPairingCode):
        verify_code("not-a-code", SECRET)
    with pytest.raises(InvalidPairingCode):
        verify_code("X1.foo.123.abc", SECRET)


def test_verify_rejects_expired():
    issued = int(time.time()) - 25 * 3600
    code = mint_code("charles@example.com", SECRET, now=issued)
    with pytest.raises(InvalidPairingCode):
        verify_code(code, SECRET)


def test_verify_handles_dotted_emails():
    code = mint_code("first.last@some.co.uk", SECRET)
    parsed = verify_code(code, SECRET)
    assert parsed.email == "first.last@some.co.uk"


def test_verify_rejects_future_codes():
    issued = int(time.time()) + 3600  # 1h in the future
    code = mint_code("charles@example.com", SECRET, now=issued)
    with pytest.raises(InvalidPairingCode):
        verify_code(code, SECRET)
