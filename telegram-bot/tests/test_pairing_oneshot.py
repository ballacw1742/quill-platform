"""Sprint-4 fix #2: pairing codes are one-shot.

Codes still expire (HMAC TTL handled by `pairing.verify_code`); on top of that
each successfully-decoded code can be redeemed exactly once.
"""

from __future__ import annotations

import time

import pytest

from quill_bot.dedup import DedupStore
from quill_bot.handlers import start
from quill_bot.pairing import mint_code


@pytest.mark.asyncio
async def test_first_redemption_succeeds(bot_config, fake_api, tmp_path) -> None:
    store = DedupStore(tmp_path / "dedup.db")
    code = mint_code("charles@example.com", bot_config.telegram_pairing_secret)
    reply = await start.handle_start(
        config=bot_config,
        api=fake_api,
        chat_id=1234567,
        args=[code],
        dedup_store=store,
    )
    assert "paired" in reply.lower() or "connected" in reply.lower()
    assert len(fake_api.pair_calls) == 1


@pytest.mark.asyncio
async def test_second_redemption_rejected(bot_config, fake_api, tmp_path) -> None:
    store = DedupStore(tmp_path / "dedup.db")
    code = mint_code("charles@example.com", bot_config.telegram_pairing_secret)
    r1 = await start.handle_start(
        config=bot_config,
        api=fake_api,
        chat_id=1234567,
        args=[code],
        dedup_store=store,
    )
    assert "paired" in r1.lower() or "connected" in r1.lower()
    r2 = await start.handle_start(
        config=bot_config,
        api=fake_api,
        chat_id=9999999,
        args=[code],
        dedup_store=store,
    )
    assert "already been used" in r2.lower() or "one-shot" in r2.lower()
    # Critical: the API must NOT be called the second time.
    assert len(fake_api.pair_calls) == 1


@pytest.mark.asyncio
async def test_redemption_persists_across_restart(
    bot_config, fake_api, tmp_path
) -> None:
    db = tmp_path / "dedup.db"
    code = mint_code("charles@example.com", bot_config.telegram_pairing_secret)
    s1 = DedupStore(db)
    await start.handle_start(
        config=bot_config,
        api=fake_api,
        chat_id=1,
        args=[code],
        dedup_store=s1,
    )
    s1.close()
    s2 = DedupStore(db)
    reply = await start.handle_start(
        config=bot_config,
        api=fake_api,
        chat_id=1,
        args=[code],
        dedup_store=s2,
    )
    assert "already been used" in reply.lower()


@pytest.mark.asyncio
async def test_expired_code_rejected_before_dedup(
    bot_config, fake_api, tmp_path, monkeypatch
) -> None:
    """HMAC TTL check runs before the dedup store, so expired codes are
    caught with the existing 'invalid pairing code' branch and never poison
    the redemption table."""
    store = DedupStore(tmp_path / "dedup.db")
    # Mint a code 'in the past' so the default 24h TTL is already exceeded.
    code = mint_code(
        "charles@example.com",
        bot_config.telegram_pairing_secret,
        now=int(time.time()) - 86_400 - 60,
    )
    reply = await start.handle_start(
        config=bot_config,
        api=fake_api,
        chat_id=1,
        args=[code],
        dedup_store=store,
    )
    assert "invalid" in reply.lower()
    assert len(fake_api.pair_calls) == 0
    # And critically: dedup table never recorded the redemption attempt.
    assert store.pairing_redeemed_at(code) is None
