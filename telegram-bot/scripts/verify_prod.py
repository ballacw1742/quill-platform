"""Prod verification harness for the Quill Telegram bot (Sprint 5.5 — G7).

Drives the bot's REAL code paths (notifier.consume_websocket for lane-2
escalation pings, scheduler.run_daily_brief for the 7:00 AM brief) against a
live API + real Telegram chat, and prints the Telegram message_id of every
message actually sent — hard evidence for verification reports.

Usage (env must carry TELEGRAM_BOT_TOKEN, QUILL_API_URL, AGENT_SHARED_SECRET,
DAILY_BRIEF_CHAT_ID — read from secret files, never inline):

    python telegram-bot/scripts/verify_prod.py ping-listen --timeout 120
        Connect the bot's WS consumer to $QUILL_API_URL's /ws/approvals and
        wait for the first push-worthy event (e.g. a lane-2 approval.created).
        Exits 0 after the first send, 1 on timeout.

    python telegram-bot/scripts/verify_prod.py brief
        Run the bot's daily-brief pipeline (runtime render → deterministic
        fallback) and send it to DAILY_BRIEF_CHAT_ID now.

Never modifies existing rows anywhere; the only writes are Telegram messages
(and the brief's best-effort Drive/local archive, which is its designed
behavior).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from quill_bot.api_client import QuillAPIClient
from quill_bot.config import BotConfig
from quill_bot.notifier import consume_websocket
from quill_bot.scheduler import run_daily_brief

SENT: list[dict] = []


def _build_send(bot):
    async def send(chat_id, text: str, silent: bool = False) -> None:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            disable_notification=silent,
        )
        SENT.append({"message_id": msg.message_id, "chat_id": msg.chat_id, "silent": silent})
        print(
            f"SENT message_id={msg.message_id} chat_id={msg.chat_id} "
            f"silent={silent} text[:80]={text[:80]!r}",
            flush=True,
        )

    return send


async def _ping_listen(config: BotConfig, send, timeout: float) -> int:
    stop = asyncio.Event()
    orig_send = send

    first_send = asyncio.get_event_loop().create_future()

    async def send_and_flag(chat_id, text, silent=False):
        await orig_send(chat_id, text, silent)
        if not first_send.done():
            first_send.set_result(True)

    task = asyncio.create_task(
        consume_websocket(
            config,
            target_chat_id=config.daily_brief_chat_id,
            send=send_and_flag,
            stop_event=stop,
        )
    )
    print(f"listening on {config.quill_ws_url} (timeout={timeout}s)…", flush=True)
    try:
        await asyncio.wait_for(first_send, timeout=timeout)
        rc = 0
    except TimeoutError:
        print("TIMEOUT: no push-worthy event arrived", flush=True)
        rc = 1
    finally:
        stop.set()
        task.cancel()
    return rc


async def _brief(config: BotConfig, api: QuillAPIClient, send) -> int:
    result = await run_daily_brief(config, api, send)
    print(f"brief result: {result}", flush=True)
    return 0 if result.get("delivered") else 1


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["ping-listen", "brief"])
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    config = BotConfig.from_env()
    if config.fake_token_mode:
        print("ERROR: TELEGRAM_BOT_TOKEN missing/fake — cannot verify prod", file=sys.stderr)
        return 2
    if not config.daily_brief_chat_id:
        print("ERROR: DAILY_BRIEF_CHAT_ID not set — no target chat", file=sys.stderr)
        return 2

    from telegram import Bot  # lazy import, same as bot.py

    bot = Bot(token=config.telegram_bot_token)
    send = _build_send(bot)
    api = QuillAPIClient(config, timeout=30.0)
    try:
        if args.mode == "ping-listen":
            return await _ping_listen(config, send, args.timeout)
        return await _brief(config, api, send)
    finally:
        await api.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
