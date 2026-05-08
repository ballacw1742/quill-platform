"""/health and /brief handlers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from quill_bot.api_client import QuillAPIClient, QuillAPIError

log = logging.getLogger("quill.bot.health")

# Brief delivery archives a Markdown file at /tmp/quill-drive/Quill/briefs/...
# (or to real Drive when gog is available). The /brief command reads the most
# recent archived brief from the local mirror so it works even offline.
DEFAULT_BRIEF_MIRROR = Path("/tmp/quill-drive/Quill/briefs")


async def handle_health(*, api: QuillAPIClient) -> str:
    try:
        h = await api.health()
    except QuillAPIError as e:
        return f"❌ Health check failed (HTTP {e.status})."

    ok = "🟢" if h.get("ok") else "🔴"
    audit = h.get("audit_chain", "?")
    audit_emoji = {"ok": "🟢", "broken": "🔴", "empty": "⚪️"}.get(audit, "⚪️")
    return (
        f"*Quill fleet health* {ok}\n"
        f"DB: `{h.get('db')}`\n"
        f"Pending: `{h.get('queue_depth_pending')}` · "
        f"Executed: `{h.get('queue_depth_executed')}`\n"
        f"Audit chain: {audit_emoji} `{audit}` (length `{h.get('audit_chain_length')}`)\n"
        f"SLA breaches open: `{h.get('sla_breaches_open')}`\n"
        f"Version: `{h.get('version')}`"
    )


def handle_brief(brief_root: Path = DEFAULT_BRIEF_MIRROR) -> str:
    """Return the most recent archived Daily Brief, or a placeholder."""
    if not brief_root.exists():
        return "📰 No Daily Brief has run yet. The first one lands at 7:00 AM ET."
    candidates = sorted(brief_root.glob("*-daily.md"), reverse=True)
    if not candidates:
        return "📰 No Daily Brief archived yet. The first one lands at 7:00 AM ET."
    latest = candidates[0]
    try:
        content = latest.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("could not read brief %s: %s", latest, e)
        return f"❌ Could not read the latest brief ({latest.name})."
    if len(content) > 3500:
        content = content[:3500] + "\n…\n_(truncated — full brief on Drive)_"
    return f"*Daily Brief — {latest.stem}*\n_(archived {datetime.fromtimestamp(latest.stat().st_mtime, UTC).isoformat()})_\n\n{content}"
