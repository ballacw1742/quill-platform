"""Quill Telegram Bot — main entry point.

Usage:
    quill-bot run            # long-poll forever
    quill-bot mint-pair --email charles@x.com   # admin: mint a pairing code

The actual python-telegram-bot wiring is kept thin; the core command logic
lives in `handlers/` so it's testable without spinning up a real bot.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

import structlog

from quill_bot import __version__
from quill_bot.api_client import QuillAPIClient
from quill_bot.config import BotConfig
from quill_bot.conversation import get_store as get_conv_store
from quill_bot.dedup import get_store as get_dedup_store
from quill_bot.handlers import decisions, health, nl, queue, start, voice
from quill_bot.handlers import help_text
from quill_bot.llm import ConversationalLLM
from quill_bot.notifier import consume_websocket, poll_health
from quill_bot.pairing import mint_code
from quill_bot.scheduler import QuillScheduler
from quill_bot.sentry import init as sentry_init
from quill_bot.transcription import WhisperClient

log = structlog.get_logger("quill.bot")


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def _run_bot(config: BotConfig) -> None:
    """Real bot loop. Imports python-telegram-bot lazily so test envs without
    the full lib still work."""
    sentry_init(config.sentry_dsn, environment=config.environment)
    api = QuillAPIClient(config)
    log.info("bot.starting", api_url=config.quill_api_url, fake=config.fake_token_mode)

    if config.fake_token_mode:
        log.warning(
            "bot.fake_token_mode — running stubbed; no Telegram I/O will occur"
        )
        await _run_stub_loop(config, api)
        return

    from telegram import BotCommand, Update  # type: ignore
    from telegram.ext import (  # type: ignore
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )

    async def send_message(chat_id: str | int, text: str, silent: bool = False) -> None:
        await app.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            disable_notification=silent,
            disable_web_page_preview=False,
        )

    async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        username = update.effective_user.username if update.effective_user else None
        reply = await start.handle_start(
            config=config,
            api=api,
            chat_id=chat_id,
            args=ctx.args,
            telegram_username=username,
        )
        await update.message.reply_markdown(reply)

    async def cmd_queue(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        page = 0
        if ctx.args:
            try:
                page = max(0, int(ctx.args[0]) - 1)
            except ValueError:
                pass
        reply = await queue.handle_queue(api=api, page=page)
        await update.message.reply_markdown(reply)

    async def cmd_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        reply = await decisions.handle_approve(
            api=api, config=config, args=ctx.args, user_id=str(update.effective_user.id)
        )
        await update.message.reply_markdown(reply, disable_web_page_preview=False)

    async def cmd_reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        reply = await decisions.handle_reject(
            api=api, config=config, args=ctx.args, user_id=str(update.effective_user.id)
        )
        await update.message.reply_markdown(reply, disable_web_page_preview=False)

    async def cmd_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        reply = await decisions.handle_edit(
            api=api, config=config, args=ctx.args, user_id=str(update.effective_user.id)
        )
        await update.message.reply_markdown(reply, disable_web_page_preview=False)

    async def cmd_escalate(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        reply = await decisions.handle_escalate(
            api=api, config=config, args=ctx.args, user_id=str(update.effective_user.id)
        )
        await update.message.reply_markdown(reply, disable_web_page_preview=False)

    async def cmd_health(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        reply = await health.handle_health(api=api)
        await update.message.reply_markdown(reply)

    async def cmd_brief(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        reply = health.handle_brief()
        await update.message.reply_markdown(reply)

    async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_markdown(help_text())

    # Build the conversational LLM (lazy: only constructed in real-bot mode
    # so test envs don't need ANTHROPIC_API_KEY).
    try:
        from anthropic import Anthropic  # type: ignore
        anthropic_client = Anthropic()
        llm = ConversationalLLM(anthropic_client)
        log.info("bot.llm_initialised model=%s", llm.model)
    except Exception as e:  # noqa: BLE001
        log.warning("bot.llm_init_failed err=%s — NL handler will reply with errors", e)
        llm = None  # type: ignore[assignment]

    # Whisper client for voice notes (Phase F.2). Initialised even when
    # OPENAI_API_KEY is unset so the voice handler can give a graceful
    # "voice notes need an API key" reply instead of crashing.
    import os as _os
    whisper = WhisperClient(api_key=_os.environ.get("OPENAI_API_KEY"))
    if whisper.is_available:
        log.info("bot.whisper_initialised model=%s", whisper.model)
    else:
        log.warning("bot.whisper_unconfigured — voice notes will reply with refusal")

    async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = int(update.effective_chat.id)
        get_conv_store().reset(chat_id)
        ctx.user_data.pop("nl_pending_dispatches", None)
        await update.message.reply_markdown(
            "🧹 Conversation cleared. What can I help with?"
        )

    app: Any = (
        Application.builder()
        .token(config.telegram_bot_token)
        .build()
    )
    # Inject deps for the NL handler (it reads from app.bot_data).
    app.bot_data["api"] = api
    app.bot_data["config"] = config
    app.bot_data["llm"] = llm
    app.bot_data["conv_store"] = get_conv_store()
    app.bot_data["dedup_store"] = get_dedup_store()
    app.bot_data["whisper"] = whisper

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("reject", cmd_reject))
    app.add_handler(CommandHandler("edit", cmd_edit))
    app.add_handler(CommandHandler("escalate", cmd_escalate))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("brief", cmd_brief))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("help", cmd_help))

    # Confirmation buttons for proposed dispatches (registered before the
    # NL fallthrough so callbacks aren't swallowed).
    app.add_handler(
        CallbackQueryHandler(nl.handle_nl_confirm, pattern=r"^nl:(confirm|cancel):")
    )

    # NL handler is the LAST text handler — catches any text message that
    # didn't match a slash command.
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, nl.handle_nl_message)
    )

    # Voice-note handler (Phase F.2). Registered AFTER text/command handlers
    # so command and text routes win whenever they apply; filters.VOICE is
    # disjoint from filters.TEXT in practice but ordering keeps it tidy.
    app.add_handler(MessageHandler(filters.VOICE, voice.handle_voice_message))

    # Register slash commands with Telegram on startup
    async def _post_init(application: Any) -> None:
        await application.bot.set_my_commands(
            [BotCommand(name, desc) for name, desc in [
                ("start", "Pair this chat to your Quill account"),
                ("queue", "List pending approvals"),
                ("approve", "Approve <id>"),
                ("reject", "Reject <id> <reason>"),
                ("edit", "Edit <id>"),
                ("escalate", "Escalate <id> to Lane 3"),
                ("health", "Fleet health"),
                ("brief", "Daily Brief"),
                ("reset", "Clear conversation memory"),
                ("help", "Show command list"),
            ]]
        )

    app.post_init = _post_init

    # Side tasks: scheduler + WS consumer + health poller
    scheduler = QuillScheduler(config, api, send_message)
    scheduler.start()

    target_chat = config.daily_brief_chat_id
    side_tasks: list[asyncio.Task] = []
    if target_chat:
        side_tasks.append(
            asyncio.create_task(
                consume_websocket(
                    config, target_chat_id=target_chat, send=send_message
                )
            )
        )
        side_tasks.append(
            asyncio.create_task(
                poll_health(
                    config, api, target_chat_id=target_chat, send=send_message
                )
            )
        )

    try:
        async with app:
            await app.initialize()
            await app.start()
            await app.updater.start_polling()
            log.info("bot.polling_started")
            # Park until cancelled
            await asyncio.Event().wait()
    finally:
        for t in side_tasks:
            t.cancel()
        await scheduler.stop()
        await api.aclose()


async def _run_stub_loop(config: BotConfig, api: QuillAPIClient) -> None:
    """Fake-token mode: spin up the scheduler so /v1/admin/scheduler/jobs
    populates correctly during dev/tests, but skip Telegram polling.
    """
    async def fake_send(chat_id: str | int, text: str, silent: bool = False) -> None:
        log.info("[fake-send]", chat_id=chat_id, silent=silent, text=text[:120])

    scheduler = QuillScheduler(config, api, fake_send)
    scheduler.start()
    try:
        # Heartbeat once explicitly so /v1/admin/scheduler/jobs has data ASAP.
        await scheduler.push_heartbeat()
        await asyncio.Event().wait()
    finally:
        await scheduler.stop()
        await api.aclose()


# ---------------------------------------------------------------------------
# Click CLI
# ---------------------------------------------------------------------------
def _parse_argv(argv: list[str]) -> dict[str, Any]:
    """Tiny hand-rolled argparser to avoid an extra dependency.

    Subcommands:
      run
      mint-pair --email <email>
      version
    """
    if not argv or argv[0] in ("run",):
        return {"cmd": "run"}
    if argv[0] in ("-h", "--help", "help"):
        return {"cmd": "help"}
    if argv[0] in ("-v", "--version", "version"):
        return {"cmd": "version"}
    if argv[0] == "mint-pair":
        email = None
        for i, a in enumerate(argv[1:]):
            if a == "--email" and i + 2 < len(argv):
                email = argv[i + 2]
        return {"cmd": "mint-pair", "email": email}
    return {"cmd": "unknown", "raw": argv}


def _print_help() -> None:
    print(
        "quill-bot — Quill Telegram bot\n\n"
        "Subcommands:\n"
        "  run                       Start the bot (long-poll)\n"
        "  mint-pair --email <e>     Generate a /start pairing code\n"
        "  version                   Print version\n"
        "  help                      Show this help\n"
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parsed = _parse_argv(argv)
    cmd = parsed.get("cmd")

    if cmd == "version":
        print(f"quill-bot {__version__}")
        return 0
    if cmd == "help":
        _print_help()
        return 0
    if cmd == "mint-pair":
        cfg = BotConfig.from_env()
        email = parsed.get("email")
        if not email:
            print("error: --email is required", file=sys.stderr)
            return 2
        code = mint_code(email, cfg.telegram_pairing_secret)
        print(code)
        return 0
    if cmd == "unknown":
        print(f"unknown command: {parsed.get('raw')}", file=sys.stderr)
        _print_help()
        return 2

    # cmd == "run"
    cfg = BotConfig.from_env()
    _configure_logging(cfg.log_level)
    try:
        asyncio.run(_run_bot(cfg))
    except KeyboardInterrupt:
        log.info("bot.shutdown_requested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
