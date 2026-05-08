"""/approve, /reject, /edit, /escalate handlers.

The actual decision endpoint requires a WebAuthn assertion which Telegram
can't perform. Every command therefore generates a short-lived deep link
to the web UI's passkey challenge. Default TTL: 60 seconds.
"""

from __future__ import annotations

import json
import logging

from quill_bot.api_client import QuillAPIClient, QuillAPIError
from quill_bot.config import BotConfig
from quill_bot.deeplink import make as make_deeplink

log = logging.getLogger("quill.bot.decisions")


async def handle_approve(
    *,
    api: QuillAPIClient,
    config: BotConfig,
    args: list[str],
    user_id: str | None = None,
) -> str:
    if not args:
        return "Usage: `/approve <id>`"
    approval_id = args[0]
    try:
        item = await api.get_approval(approval_id)
    except QuillAPIError as e:
        if e.status == 404:
            return f"❌ Approval `{approval_id}` not found."
        return f"❌ Lookup failed (HTTP {e.status})."

    if item.get("status") != "pending":
        return f"⚠️ Approval `{approval_id[:8]}` is no longer pending (status: `{item.get('status')}`)."

    link = make_deeplink(
        approval_id=approval_id,
        intent="approve",
        secret=config.deeplink_signing_secret,
        base_url=config.quill_web_base_url,
        user_id=user_id,
        ttl_seconds=config.deeplink_ttl_seconds,
    )
    return (
        f"🔐 *Approve `{approval_id[:8]}`*\n"
        f"Workflow: `{item.get('workflow')}`\n\n"
        f"[Tap here to approve with passkey]({link})\n"
        f"_Link expires in {config.deeplink_ttl_seconds}s._"
    )


async def handle_reject(
    *,
    api: QuillAPIClient,
    config: BotConfig,
    args: list[str],
    user_id: str | None = None,
) -> str:
    if len(args) < 2:
        return "Usage: `/reject <id> <reason…>`"
    approval_id = args[0]
    reason = " ".join(args[1:])
    try:
        item = await api.get_approval(approval_id)
    except QuillAPIError as e:
        if e.status == 404:
            return f"❌ Approval `{approval_id}` not found."
        return f"❌ Lookup failed (HTTP {e.status})."
    if item.get("status") != "pending":
        return f"⚠️ Approval `{approval_id[:8]}` is no longer pending."
    link = make_deeplink(
        approval_id=approval_id,
        intent="reject",
        secret=config.deeplink_signing_secret,
        base_url=config.quill_web_base_url,
        user_id=user_id,
        ttl_seconds=config.deeplink_ttl_seconds,
        extra={"reason": reason},
    )
    return (
        f"🔐 *Reject `{approval_id[:8]}`*\n"
        f"Reason: _{reason}_\n\n"
        f"[Tap here to confirm rejection with passkey]({link})\n"
        f"_Link expires in {config.deeplink_ttl_seconds}s._"
    )


async def handle_edit(
    *,
    api: QuillAPIClient,
    config: BotConfig,
    args: list[str],
    user_id: str | None = None,
) -> str:
    if not args:
        return "Usage: `/edit <id>`"
    approval_id = args[0]
    try:
        item = await api.get_approval(approval_id)
    except QuillAPIError as e:
        if e.status == 404:
            return f"❌ Approval `{approval_id}` not found."
        return f"❌ Lookup failed (HTTP {e.status})."

    payload_preview = json.dumps(item.get("payload") or {}, indent=2, default=str)
    if len(payload_preview) > 1500:
        payload_preview = payload_preview[:1500] + "\n…<truncated>"

    link = make_deeplink(
        approval_id=approval_id,
        intent="edit",
        secret=config.deeplink_signing_secret,
        base_url=config.quill_web_base_url,
        user_id=user_id,
        ttl_seconds=config.deeplink_ttl_seconds,
    )
    return (
        f"✏️ *Edit `{approval_id[:8]}`*\n"
        f"Workflow: `{item.get('workflow')}`\n\n"
        f"```json\n{payload_preview}\n```\n"
        f"[Open editor (passkey required)]({link})\n"
        f"_Link expires in {config.deeplink_ttl_seconds}s._"
    )


async def handle_escalate(
    *,
    api: QuillAPIClient,
    config: BotConfig,
    args: list[str],
    user_id: str | None = None,
) -> str:
    if not args:
        return "Usage: `/escalate <id>`"
    approval_id = args[0]
    try:
        item = await api.get_approval(approval_id)
    except QuillAPIError as e:
        if e.status == 404:
            return f"❌ Approval `{approval_id}` not found."
        return f"❌ Lookup failed (HTTP {e.status})."
    if item.get("lane", 0) >= 3:
        return f"ℹ️ `{approval_id[:8]}` is already Lane 3."
    # Escalation is a state mutation that requires audit-chained admin action.
    # We still send through the passkey deep link for the actual escalate write.
    link = make_deeplink(
        approval_id=approval_id,
        intent="approve",  # web UI handles intent=escalate as a sub-flow
        secret=config.deeplink_signing_secret,
        base_url=config.quill_web_base_url,
        user_id=user_id,
        ttl_seconds=config.deeplink_ttl_seconds,
        extra={"action": "escalate"},
    )
    return (
        f"⬆️ *Escalate `{approval_id[:8]}` to Lane 3*\n"
        f"Workflow: `{item.get('workflow')}`\n\n"
        f"[Confirm escalation with passkey]({link})\n"
        f"_Link expires in {config.deeplink_ttl_seconds}s._"
    )
