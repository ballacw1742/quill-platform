"""Voice-note handler (Phase F.2 — Commit 2).

Charles records a Telegram voice note → bot transcribes via Whisper →
the transcript is fed into the existing conversational LLM loop exactly
as if he had typed it. The handler mirrors `nl.py` closely:

    Telegram VOICE update
       │
       ▼
    handle_voice_message
       ├── pairing gate (DedupStore)
       ├── Whisper-availability gate (graceful refusal if no API key)
       ├── ack: "Got it ✓ (transcribing...)"
       ├── download voice file via Bot.get_file().download_as_bytearray()
       ├── transcribe via WhisperClient
       ├── empty transcript → "couldn't make out" reply
       ├── append user transcript to ConversationStore (with voice metadata)
       ├── ConversationalLLM.turn(...)
       ├── persist assistant + tool-call evidence (same as nl.py)
       └── send reply (Markdown)

Errors are caught and surfaced as graceful fallback messages — the bot
never just dies on a voice note.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from quill_bot import sentry as sentry_helper
from quill_bot.api_client import QuillAPIClient
from quill_bot.config import BotConfig
from quill_bot.conversation import ConversationStore, get_store as get_conv_store
from quill_bot.dedup import DedupStore, get_store as get_dedup_store
from quill_bot.handlers.nl import (
    CANCEL_BTN_PREFIX,
    CONFIRM_BTN_PREFIX,
    CONFIRM_PROMPT_SUFFIX,
    GENERIC_ERROR_REPLY,
    UNPAIRED_REPLY,
)
from quill_bot.llm import AssistantTurn, ConversationalLLM
from quill_bot.tools import ChatContext
from quill_bot.transcription import (
    TranscriptionAPIError,
    TranscriptionError,
    TranscriptionNotConfigured,
    TranscriptionResult,
    TranscriptionTooLarge,
    WhisperClient,
)

log = logging.getLogger("quill.bot.voice")


# ---------------------------------------------------------------------------
# User-facing copy.
# ---------------------------------------------------------------------------
WHISPER_UNCONFIGURED_REPLY = (
    "🎙️ Voice notes need an OpenAI API key on the server. "
    "For now, type your message instead."
)

ACK_REPLY = "Got it ✓ (transcribing…)"

EMPTY_TRANSCRIPT_REPLY = (
    "🎙️ I couldn't make out the audio. Try recording again in a quieter spot, "
    "or type your message instead."
)

TOO_LARGE_REPLY = (
    "🎙️ That voice note is over Whisper's 25 MB cap. Try a shorter recording."
)

TRANSCRIBE_FAILED_REPLY = (
    "🎙️ I couldn't transcribe that one — Whisper failed. Try again in a moment, "
    "or type your message instead."
)

DOWNLOAD_FAILED_REPLY = (
    "🎙️ I couldn't download the voice file from Telegram. Try sending it again."
)


# ---------------------------------------------------------------------------
# Pure-logic core (testable without spinning up Telegram).
# ---------------------------------------------------------------------------
async def process_voice_message(
    *,
    audio_bytes: bytes,
    chat_id: int,
    api: QuillAPIClient,
    config: BotConfig,
    llm: ConversationalLLM,
    conv_store: ConversationStore,
    dedup_store: DedupStore,
    whisper: WhisperClient,
    mime_type: str = "audio/ogg",
    filename: str = "voice.ogg",
) -> tuple[str, list[dict[str, Any]], TranscriptionResult | None]:
    """Run one voice-note turn end-to-end.

    Returns (reply_text, pending_dispatches, transcription_or_None). The
    transcription is None on early-exit paths (unpaired, no key, too
    large, empty transcript, failures). The Telegram adapter uses the
    pending_dispatches list to decide whether to attach the Yes/No
    inline keyboard, exactly like nl.process_nl_message.
    """
    # Pairing gate.
    if not dedup_store.is_chat_paired(chat_id):
        return UNPAIRED_REPLY, [], None

    # Whisper-availability gate. Cheap, no I/O.
    if not whisper.is_available:
        return WHISPER_UNCONFIGURED_REPLY, [], None

    paired_email = dedup_store.get_paired_email(chat_id)

    # Transcribe.
    try:
        transcription = await whisper.transcribe(
            audio_bytes, mime_type=mime_type, filename=filename
        )
    except TranscriptionNotConfigured:
        # Belt-and-suspenders: shouldn't happen since we checked above.
        return WHISPER_UNCONFIGURED_REPLY, [], None
    except TranscriptionTooLarge:
        return TOO_LARGE_REPLY, [], None
    except (TranscriptionAPIError, TranscriptionError) as e:
        log.warning("voice.transcribe_failed chat_id=%s err=%s", chat_id, e)
        sentry_helper.capture_exception(e, chat_id=chat_id, where="voice.transcribe")
        return TRANSCRIBE_FAILED_REPLY, [], None
    except Exception as e:  # noqa: BLE001
        log.exception("voice.transcribe_unexpected chat_id=%s", chat_id)
        sentry_helper.capture_exception(
            e, chat_id=chat_id, where="voice.transcribe.unexpected"
        )
        return TRANSCRIBE_FAILED_REPLY, [], None

    text = (transcription.text or "").strip()
    if not text:
        return EMPTY_TRANSCRIPT_REPLY, [], transcription

    # Run the conversational turn.
    history = conv_store.history(chat_id, max_messages=24)
    ctx = ChatContext(
        api=api,
        config=config,
        chat_id=chat_id,
        user_id=paired_email,
    )

    try:
        turn: AssistantTurn = await llm.turn(text, history=history, ctx=ctx)
    except Exception as e:  # noqa: BLE001
        log.exception("voice.llm_failed chat_id=%s", chat_id)
        sentry_helper.capture_exception(e, chat_id=chat_id, where="voice.llm")
        return GENERIC_ERROR_REPLY, [], transcription

    # Persist the user message AFTER the call succeeded — same ordering as
    # nl.py so a half-completed turn doesn't poison future history.
    # Embed voice metadata in the persisted content so future LLM context
    # contains the transcript with a small "(voice note, 2.7s)" tag — that
    # mirrors how Charles thinks about it in chat scrollback.
    persisted_content = _format_voice_user_content(text, transcription)
    conv_store.append(chat_id, "user", content=persisted_content)

    # Persist assistant blocks + tool_results — identical pattern to nl.py.
    tool_calls_by_id = {tc.tool_use_id: tc for tc in turn.tool_calls}
    for blocks in turn.assistant_blocks:
        text_chunks = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        tool_use_blocks = [b for b in blocks if b.get("type") == "tool_use"]
        if tool_use_blocks:
            assistant_tcs = [
                {"id": b["id"], "name": b["name"], "input": b.get("input", {})}
                for b in tool_use_blocks
            ]
            conv_store.append(
                chat_id,
                "assistant",
                content="".join(text_chunks).strip() or None,
                tool_calls=assistant_tcs,
            )
            for b in tool_use_blocks:
                tc = tool_calls_by_id.get(b["id"])
                if tc is None:
                    continue
                conv_store.append(
                    chat_id,
                    "tool",
                    content=json.dumps(tc.result, default=str),
                    tool_call_id=b["id"],
                )

    if turn.text:
        conv_store.append(chat_id, "assistant", content=turn.text)

    # Same dispatch-confirmation surfacing as nl.py.
    pending = [
        {
            "tool_use_id": tc.tool_use_id,
            "agent_id": tc.input.get("agent_id"),
            "summary": tc.input.get("summary", ""),
            "input_payload": tc.input.get("input_payload", {}),
            "dry_run_output": tc.result.get("output") if isinstance(tc.result, dict) else None,
        }
        for tc in turn.tool_calls
        if tc.name == "dispatch_agent" and not tc.result.get("error")
    ]

    reply_text = turn.text or "(no reply)"
    return reply_text, pending, transcription


def _format_voice_user_content(text: str, transcription: TranscriptionResult) -> str:
    """Embed the transcript + a small voice-source tag so future LLM
    context sees this was a voice note.

    Format (Charles's preferred shorthand):
        [voice note · 3s] What's pending today?
    """
    duration = transcription.duration_sec or 0.0
    if duration >= 0.5:
        tag = f"[voice note · {duration:.0f}s]"
    else:
        tag = "[voice note]"
    return f"{tag} {text}"


# ---------------------------------------------------------------------------
# Telegram adapter.
# ---------------------------------------------------------------------------
async def handle_voice_message(update: Any, context: Any) -> None:
    """python-telegram-bot MessageHandler entry point for filters.VOICE."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore

    chat = update.effective_chat
    msg = update.effective_message
    if chat is None or msg is None or msg.voice is None:
        return

    chat_id = int(chat.id)
    voice = msg.voice

    bot_data = context.application.bot_data
    api: QuillAPIClient = bot_data["api"]
    config: BotConfig = bot_data["config"]
    llm: ConversationalLLM = bot_data["llm"]
    conv_store: ConversationStore = bot_data.get("conv_store") or get_conv_store()
    dedup_store: DedupStore = bot_data.get("dedup_store") or get_dedup_store()
    whisper: WhisperClient | None = bot_data.get("whisper")

    sentry_helper.tag_user(chat_id=chat_id)

    # Hard fail-safes BEFORE we attempt any download.
    if not dedup_store.is_chat_paired(chat_id):
        await msg.reply_markdown(UNPAIRED_REPLY)
        return

    if whisper is None or not whisper.is_available:
        await msg.reply_markdown(WHISPER_UNCONFIGURED_REPLY)
        return

    # Acknowledge so Charles knows we heard him during the ~1-2s download
    # + transcription window. Plain text — no Markdown drama.
    try:
        await msg.reply_text(ACK_REPLY)
    except Exception:  # noqa: BLE001
        # If the ack itself fails, log and keep going — the answer matters
        # more than the ack.
        log.warning("voice.ack_failed chat_id=%s", chat_id)

    # Cheap server-side size guard before any download attempt.
    file_size = getattr(voice, "file_size", None)
    if file_size is not None and file_size > 25 * 1024 * 1024:
        await msg.reply_markdown(TOO_LARGE_REPLY)
        return

    # Download the voice file from Telegram CDN.
    try:
        tg_file = await context.application.bot.get_file(voice.file_id)
        audio_buf = await tg_file.download_as_bytearray()
        audio_bytes = bytes(audio_buf)
    except Exception as e:  # noqa: BLE001
        log.exception("voice.download_failed chat_id=%s", chat_id)
        sentry_helper.capture_exception(e, chat_id=chat_id, where="voice.download")
        try:
            await msg.reply_markdown(DOWNLOAD_FAILED_REPLY)
        except Exception:  # noqa: BLE001
            log.exception("voice.download_failed.reply_failed")
        return

    mime_type = getattr(voice, "mime_type", None) or "audio/ogg"

    try:
        reply, pending, _transcript = await process_voice_message(
            audio_bytes=audio_bytes,
            chat_id=chat_id,
            api=api,
            config=config,
            llm=llm,
            conv_store=conv_store,
            dedup_store=dedup_store,
            whisper=whisper,
            mime_type=mime_type,
            filename=f"voice-{voice.file_id[:12]}.ogg",
        )
    except Exception as e:  # noqa: BLE001
        log.exception("voice.handler_failed chat_id=%s", chat_id)
        sentry_helper.capture_exception(e, chat_id=chat_id, where="voice.handler")
        try:
            await msg.reply_markdown(GENERIC_ERROR_REPLY)
        except Exception:  # noqa: BLE001
            log.exception("voice.handler_failed.reply_failed")
        return

    # Confirmation buttons for proposed dispatches — same pattern as nl.py.
    reply_markup = None
    if pending:
        proposals = context.user_data.setdefault("nl_pending_dispatches", {})
        idx = str(len(proposals))
        proposals[idx] = pending[0]
        cb_yes = f"{CONFIRM_BTN_PREFIX}{idx}"
        cb_no = f"{CANCEL_BTN_PREFIX}{idx}"
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Yes, do it", callback_data=cb_yes),
                    InlineKeyboardButton("❌ Cancel", callback_data=cb_no),
                ]
            ]
        )
        if not reply.rstrip().endswith("?"):
            reply = reply.rstrip() + CONFIRM_PROMPT_SUFFIX

    try:
        await msg.reply_markdown(
            reply, reply_markup=reply_markup, disable_web_page_preview=False
        )
    except Exception as e:  # noqa: BLE001
        log.warning("voice.reply_markdown_failed err=%s", e)
        try:
            await msg.reply_text(reply, reply_markup=reply_markup)
        except Exception:  # noqa: BLE001
            log.exception("voice.reply_plain_failed")


__all__ = [
    "handle_voice_message",
    "process_voice_message",
    "WHISPER_UNCONFIGURED_REPLY",
    "ACK_REPLY",
    "EMPTY_TRANSCRIPT_REPLY",
    "TOO_LARGE_REPLY",
    "TRANSCRIBE_FAILED_REPLY",
    "DOWNLOAD_FAILED_REPLY",
]
