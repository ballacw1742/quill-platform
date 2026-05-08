"""/start handler — pairing flow.

Charles runs `/start <code>` once per device. The code is minted by an admin
(via `quill-bot mint-pair --email charles@...`) and is HMAC-signed; we verify
locally then call the API to store the chat_id on the User row.
"""

from __future__ import annotations

import logging
from typing import Any

from quill_bot.api_client import QuillAPIClient, QuillAPIError
from quill_bot.config import BotConfig
from quill_bot.dedup import DedupStore, get_store
from quill_bot.pairing import InvalidPairingCode, verify_code

log = logging.getLogger("quill.bot.start")


WELCOME_PAIRED = (
    "🔗 *Telegram paired.*\n"
    "You're connected as `{email}`.\n\n"
    "Just message me in plain English. I can find approvals, summarize the "
    "day, draft updates, and more. You can also send voice notes — "
    "I'll transcribe and answer. /help for shortcuts."
)

WELCOME_NEEDS_CODE = (
    "👋 *Quill Bot*\n\n"
    "To pair this chat with your Quill account, run:\n"
    "`/start <pairing-code>`\n\n"
    "Get your code from an admin: `quill-bot mint-pair --email <you@…>`."
)

ALREADY_REDEEMED = (
    "❌ That pairing code has already been used.\n"
    "Each code is one-shot. Ask an admin to mint a new one:\n"
    "`quill-bot mint-pair --email <you@…>`."
)


async def handle_start(
    *,
    config: BotConfig,
    api: QuillAPIClient,
    chat_id: int | str,
    args: list[str],
    telegram_username: str | None = None,
    dedup_store: DedupStore | None = None,
) -> str:
    """Pure-logic handler so the same code path is unit-testable.

    Returns the markdown reply. The bot adapter calls this and forwards the
    text to Telegram.

    Sprint-4 fix #2: pairing codes are one-shot. We claim the redemption in
    a tiny SQLite store BEFORE calling the API so a reused code is rejected
    at the bot layer with a clear message; the HMAC verification still runs
    first so we never persist garbage codes.
    """
    if not args:
        return WELCOME_NEEDS_CODE

    code = args[0]
    try:
        parsed = verify_code(code, config.telegram_pairing_secret)
    except InvalidPairingCode as e:
        log.warning("pairing code rejected: %s", e)
        return f"❌ Invalid pairing code: {e}\n\nAsk an admin for a new one."

    store = dedup_store or get_store()
    if not store.claim_pairing(code, email=parsed.email, chat_id=str(chat_id)):
        log.warning(
            "pairing code re-use rejected email=%s chat=%s", parsed.email, chat_id
        )
        return ALREADY_REDEEMED

    try:
        result = await api.pair_user_telegram(
            email=parsed.email,
            chat_id=str(chat_id),
            telegram_username=telegram_username,
        )
    except QuillAPIError as e:
        log.error("pair_user_telegram failed: %s", e)
        if e.status == 404:
            return f"❌ No Quill user found for `{parsed.email}`. Ask an admin to create the user first."
        return f"❌ Pairing failed (HTTP {e.status}). Try again or contact an admin."

    return WELCOME_PAIRED.format(email=result.get("email", parsed.email))


def help_handler() -> str:
    from quill_bot.handlers import help_text
    return help_text()


__all__: list[Any] = [
    "handle_start",
    "help_handler",
    "WELCOME_NEEDS_CODE",
    "WELCOME_PAIRED",
    "ALREADY_REDEEMED",
]
