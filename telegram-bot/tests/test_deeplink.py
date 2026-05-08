"""Deep-link signing/verify tests."""

from __future__ import annotations

import time

import pytest

from quill_bot.deeplink import make, verify


SECRET = "deeplink-test-secret"
BASE = "https://web.test"


def test_make_and_verify_roundtrip():
    url = make(
        "ap-1234",
        "approve",
        secret=SECRET,
        base_url=BASE,
        user_id="u-1",
        ttl_seconds=60,
    )
    assert url.startswith(BASE + "/approvals/ap-1234/approve?t=")
    token = url.split("t=", 1)[1]
    payload = verify(token, secret=SECRET)
    assert payload.id == "ap-1234"
    assert payload.intent == "approve"
    assert payload.user_id == "u-1"


def test_verify_rejects_bad_signature():
    url = make("ap-9", "reject", secret=SECRET, base_url=BASE, ttl_seconds=60)
    token = url.split("t=", 1)[1]
    # Flip a byte in the signature
    payload_b64, sig = token.rsplit(".", 1)
    bad = payload_b64 + "." + ("0" * len(sig))
    with pytest.raises(ValueError):
        verify(bad, secret=SECRET)


def test_verify_rejects_expired():
    url = make(
        "ap-old",
        "approve",
        secret=SECRET,
        base_url=BASE,
        ttl_seconds=60,
        now=int(time.time()) - 600,
    )
    token = url.split("t=", 1)[1]
    with pytest.raises(ValueError):
        verify(token, secret=SECRET)


def test_verify_rejects_malformed():
    with pytest.raises(ValueError):
        verify("notavalidtoken", secret=SECRET)


def test_verify_rejects_wrong_secret():
    url = make("ap-1", "approve", secret=SECRET, base_url=BASE, ttl_seconds=60)
    token = url.split("t=", 1)[1]
    with pytest.raises(ValueError):
        verify(token, secret="other-secret")


def test_extra_payload_carried():
    url = make(
        "ap-7",
        "reject",
        secret=SECRET,
        base_url=BASE,
        ttl_seconds=60,
        extra={"reason": "scope creep"},
    )
    token = url.split("t=", 1)[1]
    payload = verify(token, secret=SECRET)
    assert payload.id == "ap-7"
    assert payload.intent == "reject"
