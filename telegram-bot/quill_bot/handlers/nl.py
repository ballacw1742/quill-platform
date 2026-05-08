"""Natural-language message handler (Phase B, Commit 5).

Catches every non-command text message in the bot's DM, routes it through
ConversationalLLM, and replies with plain English (with deep links inline).

Architecture:
    Telegram update
       │
       ▼
    handle_nl_message
       ├── chat-paired? (DedupStore)  → if no, send pairing instructions
       ├── load history (ConversationStore, last 24)
       ├── append user turn
       ├── ConversationalLLM.turn(...)
       ├── persist assistant text + tool-use blocks
       ├── if any dispatch_agent was called, attach inline-keyboard
       │     buttons "✅ Yes, do it" / "❌ Cancel" — user confirmation
       │     would then run a non-dry-run dispatch (Phase D will wire the
       │     actual write path; today it logs and acknowledges).
       └── send reply (Markdown formatting)

Confirmation convention (per CONVERSATIONAL_SPEC, hard rule #1):
    The bot never writes to systems of record. The system prompt instructs
    Claude to *describe* any proposed write in plain English and ask the
    user to confirm before invoking write-side tools. The only write-side
    tool today is `dispatch_agent`, and at the tool layer it ALWAYS runs
    in --no-submit (dry-run). Even so, when Claude requests a dispatch we
    surface explicit Yes/No buttons so the user can re-confirm before any
    future non-dry-run path is enabled.

Errors are caught, logged to Sentry, and surfaced as a graceful fallback
message — the bot never just dies on the user.
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
from quill_bot.llm import AssistantTurn, ConversationalLLM
from quill_bot.tools import ChatContext

log = logging.getLogger("quill.bot.nl")


UNPAIRED_REPLY = (
    "I don't recognize this chat yet. "
    "Run `/start <code>` after pairing through the Quill app — "
    "Profile → Authentication → Telegram."
)

GENERIC_ERROR_REPLY = (
    "⚠️ Hit a snag. Try again in a moment, or use /help to see slash-command shortcuts."
)

CONFIRM_PROMPT_SUFFIX = (
    "\n\n_Tap a button below to confirm._"
)

# Inline-keyboard button payloads. Format: `nl:confirm:<chat_id>:<dispatch_idx>`.
CONFIRM_BTN_PREFIX = "nl:confirm:"
CANCEL_BTN_PREFIX = "nl:cancel:"


# ---------------------------------------------------------------------------
# Pure-logic core (testable without spinning up Telegram).
# ---------------------------------------------------------------------------
async def process_nl_message(
    *,
    text: str,
    chat_id: int,
    api: QuillAPIClient,
    config: BotConfig,
    llm: ConversationalLLM,
    conv_store: ConversationStore,
    dedup_store: DedupStore,
) -> tuple[str, list[dict[str, Any]]]:
    """Run one NL turn end-to-end. Returns (reply_text, pending_dispatches).

    `pending_dispatches` is the list of dispatch_agent tool calls executed
    during this turn (in dry-run mode). The Telegram adapter uses this to
    decide whether to attach the Yes/No inline keyboard. Empty when Claude
    didn't propose any agent dispatch.
    """
    # Pairing gate. The dedup store knows which chat_ids have a redeemed
    # pairing code — that's our authoritative "is this chat known?" check.
    if not dedup_store.is_chat_paired(chat_id):
        return UNPAIRED_REPLY, []

    paired_email = dedup_store.get_paired_email(chat_id)

    # Load rolling history (oldest first; LLM trims internally too).
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
        log.exception("nl.llm_failed chat_id=%s", chat_id)
        sentry_helper.capture_exception(e, chat_id=chat_id, where="nl.llm")
        return GENERIC_ERROR_REPLY, []

    # Persist the user message AFTER the call succeeded — if the call
    # failed we don't want a half-formed turn poisoning future history.
    conv_store.append(chat_id, "user", content=text)

    # Persist each iteration's assistant block (text + any tool_use), then
    # the matching tool_result so the next turn replays correctly.
    tool_calls_by_id = {tc.tool_use_id: tc for tc in turn.tool_calls}
    for blocks in turn.assistant_blocks:
        text_chunks = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        tool_use_blocks = [b for b in blocks if b.get("type") == "tool_use"]

        # Skip the final assistant text-only block — we'll persist it as
        # the canonical assistant message below.
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
            # Now the tool_result blocks (one per tool_use) — Anthropic
            # requires these as user-role tool_result content.
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

    # Final assistant message (the user-visible reply).
    if turn.text:
        conv_store.append(chat_id, "assistant", content=turn.text)

    # Look for dispatch_agent calls — those become "pending confirmations".
    # We surface them as a separate list so the Telegram layer can render
    # inline-keyboard buttons.
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
    return reply_text, pending


# ---------------------------------------------------------------------------
# Telegram adapter. Wired into bot.py via MessageHandler.
# ---------------------------------------------------------------------------
async def handle_nl_message(update: Any, context: Any) -> None:
    """python-telegram-bot MessageHandler entry point.

    Imports are local so test envs without python-telegram-bot still work.
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore

    chat = update.effective_chat
    msg = update.effective_message
    if chat is None or msg is None or not msg.text:
        return

    chat_id = int(chat.id)
    text = msg.text.strip()

    # Pull dependencies from bot_data (registered in bot.py).
    bot_data = context.application.bot_data
    api: QuillAPIClient = bot_data["api"]
    config: BotConfig = bot_data["config"]
    llm: ConversationalLLM = bot_data["llm"]
    conv_store: ConversationStore = bot_data.get("conv_store") or get_conv_store()
    dedup_store: DedupStore = bot_data.get("dedup_store") or get_dedup_store()

    sentry_helper.tag_user(chat_id=chat_id)

    try:
        reply, pending = await process_nl_message(
            text=text,
            chat_id=chat_id,
            api=api,
            config=config,
            llm=llm,
            conv_store=conv_store,
            dedup_store=dedup_store,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("nl.handler_failed chat_id=%s", chat_id)
        sentry_helper.capture_exception(e, chat_id=chat_id, where="nl.handler")
        await msg.reply_text(GENERIC_ERROR_REPLY)
        return

    # If Claude proposed a dispatch, stash the proposal under user_data and
    # render confirmation buttons. The CallbackQueryHandler in bot.py reads
    # the same user_data to execute (or cancel) on click.
    reply_markup = None
    if pending:
        # Index by ordinal so the callback_data fits in 64 bytes.
        proposals = context.user_data.setdefault("nl_pending_dispatches", {})
        # Clean older proposals (>10 min) — cheap heuristic.
        for k in list(proposals.keys()):
            try:
                if k.startswith("expired-"):
                    proposals.pop(k, None)
            except Exception:  # noqa: BLE001
                pass
        idx = str(len(proposals))
        proposals[idx] = pending[0]  # only support one pending at a time
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
        # Markdown parse errors etc — fall back to plain text so the reply
        # still gets through.
        log.warning("nl.reply_markdown_failed err=%s", e)
        try:
            await msg.reply_text(reply, reply_markup=reply_markup)
        except Exception:  # noqa: BLE001
            log.exception("nl.reply_plain_failed")


# ---------------------------------------------------------------------------
# Confirmation callback (handles the inline keyboard "Yes / No" buttons).
# ---------------------------------------------------------------------------
async def handle_nl_confirm(update: Any, context: Any) -> None:
    """CallbackQueryHandler for the Yes/No buttons attached to dispatch
    proposals. Today this is a thin acknowledgement: the dispatch already
    ran in dry-run when Claude called the tool, so there's nothing more
    to *write* yet (Phase B is read-mostly). On Yes we acknowledge that
    the dry-run output was accepted; on No we drop the proposal.

    Phase D will replace the body of the Yes branch with a non-dry-run
    runtime invocation that submits to the Approval Queue.
    """
    query = update.callback_query
    if query is None:
        return
    data = query.data or ""
    await query.answer()

    proposals: dict[str, dict[str, Any]] = context.user_data.get(
        "nl_pending_dispatches", {}
    )

    if data.startswith(CONFIRM_BTN_PREFIX):
        idx = data[len(CONFIRM_BTN_PREFIX):]
        proposal = proposals.pop(idx, None)
        if proposal is None:
            await query.edit_message_text(
                "⚠️ That confirmation expired. Ask me again and I'll re-propose."
            )
            return
        agent = proposal.get("agent_id") or "unknown-agent"
        await query.edit_message_text(
            f"✅ Acknowledged. I'll route this through `{agent}` once the "
            f"non-dry-run path is enabled (Phase D). Dry-run output already "
            f"shown above is what the agent would produce.",
            parse_mode="Markdown",
        )
        return

    if data.startswith(CANCEL_BTN_PREFIX):
        idx = data[len(CANCEL_BTN_PREFIX):]
        proposals.pop(idx, None)
        await query.edit_message_text("❌ Cancelled. No action taken.")
        return


__all__ = [
    "process_nl_message",
    "handle_nl_message",
    "handle_nl_confirm",
    "UNPAIRED_REPLY",
    "GENERIC_ERROR_REPLY",
    "CONFIRM_BTN_PREFIX",
    "CANCEL_BTN_PREFIX",
]
