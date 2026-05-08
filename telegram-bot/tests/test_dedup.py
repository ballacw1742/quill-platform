"""Tests for the persistent dedup store (Sprint 4 fix #1 & #2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from quill_bot.dedup import DedupStore, REMINDER_KINDS, reset_store_for_tests


@pytest.fixture()
def store(tmp_path: Path) -> DedupStore:
    return reset_store_for_tests(tmp_path / "dedup.db")


# ---------------------------------------------------------------------------
# Reminder dedup
# ---------------------------------------------------------------------------
def test_claim_reminder_first_time_returns_true(store: DedupStore) -> None:
    assert store.claim_reminder("appr-1", "lane2_4h") is True


def test_claim_reminder_second_time_returns_false(store: DedupStore) -> None:
    assert store.claim_reminder("appr-1", "lane2_4h") is True
    assert store.claim_reminder("appr-1", "lane2_4h") is False


def test_each_kind_is_independent(store: DedupStore) -> None:
    for kind in REMINDER_KINDS:
        assert store.claim_reminder("appr-x", kind) is True
        assert store.claim_reminder("appr-x", kind) is False


def test_different_approvals_dont_collide(store: DedupStore) -> None:
    assert store.claim_reminder("a", "lane2_4h") is True
    assert store.claim_reminder("b", "lane2_4h") is True
    assert store.claim_reminder("a", "lane2_4h") is False
    assert store.claim_reminder("b", "lane2_4h") is False


def test_reset_approval_clears_rows(store: DedupStore) -> None:
    store.claim_reminder("a", "lane2_4h")
    store.claim_reminder("a", "lane2_8h")
    assert store.reset_approval("a") == 2
    # Now we can re-claim (lifecycle is "approval terminated, brand new one starts")
    assert store.claim_reminder("a", "lane2_4h") is True


def test_unknown_kind_warns_but_still_works(
    store: DedupStore, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="quill.bot.dedup"):
        assert store.claim_reminder("a", "made_up_kind") is True
    assert "unknown reminder_kind" in caplog.text


# ---------------------------------------------------------------------------
# Bot-restart durability — recreate store on the same file
# ---------------------------------------------------------------------------
def test_persists_across_restart(tmp_path: Path) -> None:
    db = tmp_path / "dedup.db"
    s1 = DedupStore(db)
    assert s1.claim_reminder("appr-9", "lane2_4h") is True
    s1.close()
    # Simulate bot restart
    s2 = DedupStore(db)
    assert s2.claim_reminder("appr-9", "lane2_4h") is False
    assert s2.reminder_sent("appr-9", "lane2_4h") is True


# ---------------------------------------------------------------------------
# Pairing-code one-shot
# ---------------------------------------------------------------------------
def test_claim_pairing_first_redemption_succeeds(store: DedupStore) -> None:
    assert store.claim_pairing("code-1", email="x@y.z", chat_id="42") is True


def test_claim_pairing_second_redemption_fails(store: DedupStore) -> None:
    assert store.claim_pairing("code-1", email="x@y.z", chat_id="42") is True
    assert store.claim_pairing("code-1", email="x@y.z", chat_id="42") is False
    # Even with a different chat_id (e.g. attacker reusing a code from another chat)
    assert store.claim_pairing("code-1", email="x@y.z", chat_id="99") is False


def test_pairing_persists_across_restart(tmp_path: Path) -> None:
    db = tmp_path / "dedup.db"
    s1 = DedupStore(db)
    assert s1.claim_pairing("code-q", email="a@b.c", chat_id="1") is True
    s1.close()
    s2 = DedupStore(db)
    assert s2.claim_pairing("code-q", email="a@b.c", chat_id="1") is False
    assert s2.pairing_redeemed_at("code-q") is not None
