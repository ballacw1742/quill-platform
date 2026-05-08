"""Telegram bot command handlers (Sprint 2.4 + Phase B)."""

from quill_bot.handlers import decisions, health, nl, queue, start, voice

__all__ = ["decisions", "health", "nl", "queue", "start", "voice"]


COMMAND_LIST = [
    ("start", "Pair this Telegram chat to your Quill account"),
    ("queue", "List pending Lane 2/3 approvals"),
    ("approve", "Approve <id> via passkey deep-link"),
    ("reject", "Reject <id> <reason> via passkey deep-link"),
    ("edit", "Edit <id> payload (deep-link to web)"),
    ("escalate", "Escalate <id> to Lane 3"),
    ("health", "Quill fleet health summary"),
    ("brief", "Latest Daily Brief"),
    ("reset", "Clear this chat's conversation memory"),
    ("help", "Show this help"),
]


def help_text() -> str:
    """Phase-B help text.

    Natural language is the *primary* interface; slash commands are
    shortcuts. Kept under 200 words so it fits on one Telegram screen.
    """
    return (
        "*Quill Bot — How to use me*\n\n"
        "💬 *Just message me in plain English.*\n"
        "I can search the Approval Queue, summarize your day, draft updates, "
        "explain why something is flagged, and pull live data from the runtime. "
        "Examples:\n"
        "• _what's pending?_\n"
        "• _any chiller items?_\n"
        "• _what did I sign yesterday?_\n"
        "• _draft a status update for this week_\n\n"
        "🎙️ *Voice notes work too.* Hold the mic in Telegram, talk, send. "
        "I'll transcribe via Whisper and answer the same way.\n\n"
        "I'll never approve, sign, or send anything for you — for write "
        "actions I produce a 60-second deep link to the web app where "
        "Face ID does the ceremony.\n\n"
        "*Slash-command shortcuts*\n"
        "`/queue` — pending approvals\n"
        "`/approve <id>` · `/reject <id> <reason>` · `/edit <id>` · `/escalate <id>`\n"
        "`/health` — fleet status · `/brief` — latest Daily Brief\n"
        "`/reset` — clear my memory of this chat\n"
        "`/start <code>` — pair a new chat"
    )
