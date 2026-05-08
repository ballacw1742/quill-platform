"""/queue handler — paginated list of pending Lane 2/3 items."""

from __future__ import annotations

import logging
from typing import Any

from quill_bot.api_client import QuillAPIClient, QuillAPIError

log = logging.getLogger("quill.bot.queue")

PAGE_SIZE = 5


def _format_item(item: dict[str, Any]) -> str:
    lane = item.get("lane", "?")
    flags: list[str] = []
    if item.get("priority") == "critical":
        flags.append("🚨")
    if (item.get("payload") or {}).get("safety_critical"):
        flags.append("⚠️")
    if (item.get("payload") or {}).get("critical_path"):
        flags.append("📍")
    flag_str = "".join(flags)
    sla_due = item.get("sla_due_at") or "—"
    workflow = item.get("workflow", "?")
    short_id = (item.get("id") or "")[:8]
    confidence = item.get("agent_confidence")
    conf = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "?"
    return (
        f"{flag_str}*L{lane}* `{short_id}` — `{workflow}` "
        f"(conf {conf}, SLA {sla_due})"
    )


async def handle_queue(
    *,
    api: QuillAPIClient,
    page: int = 0,
    lane: int | None = None,
) -> str:
    """List pending items, paginated PAGE_SIZE per page."""
    try:
        items = await api.list_pending(
            lane=lane, limit=PAGE_SIZE, offset=page * PAGE_SIZE
        )
    except QuillAPIError as e:
        log.error("list_pending failed: %s", e)
        return f"❌ Could not fetch queue (HTTP {e.status})."

    if not items:
        if page == 0:
            return "✅ Nothing pending. The queue is empty."
        return f"📭 No items on page {page + 1}."

    header = f"*Pending approvals — page {page + 1}*"
    if lane is not None:
        header += f" _(lane {lane} only)_"
    body = "\n".join(_format_item(it) for it in items)

    nav = []
    if page > 0:
        nav.append(f"`/queue {page}` ← prev")
    if len(items) == PAGE_SIZE:
        nav.append(f"`/queue {page + 2}` next →")
    nav_str = "\n\n" + " · ".join(nav) if nav else ""

    return f"{header}\n\n{body}{nav_str}"
