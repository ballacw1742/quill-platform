"""Telegram bot command handlers (Sprint 2.4)."""

from quill_bot.handlers import decisions, health, queue, start

__all__ = ["decisions", "health", "queue", "start"]


COMMAND_LIST = [
    ("start", "Pair this Telegram chat to your Quill account"),
    ("queue", "List pending Lane 2/3 approvals"),
    ("approve", "Approve <id> via passkey deep-link"),
    ("reject", "Reject <id> <reason> via passkey deep-link"),
    ("edit", "Edit <id> payload (deep-link to web)"),
    ("escalate", "Escalate <id> to Lane 3"),
    ("health", "Quill fleet health summary"),
    ("brief", "Latest Daily Brief"),
    ("help", "Show this help"),
]


def help_text() -> str:
    lines = ["*Quill Bot — Commands*"]
    for name, desc in COMMAND_LIST:
        lines.append(f"`/{name}` — {desc}")
    return "\n".join(lines)
