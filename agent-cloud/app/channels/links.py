"""Channel pairing/link lifecycle + inbound resolution + turn runner.

Contract: CHANNELS.md. This module is the service layer behind both the
pairing endpoints (web → api bridge → agent-cloud) and the inbound webhooks.

Discipline (identical to directory.py/agents.py): every tenant-scoped query
filters tenant_id at the app layer AND runs inside tenant_session() so RLS
is the second belt. The ONE cross-tenant scan — resolving an inbound
platform identity to its (tenant, agent), which is unauthenticated w.r.t.
our tenants (the platform id is all we have) — runs under the admin RLS
policy, exactly like the scheduler claim and the approvals reconcile sweep.
Once resolved, every per-link write runs tenant-scoped again.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa

from app import events as events_mod
from app import ratelimit as ratelimit_mod
from app.channels.base import PLATFORMS, InboundMessage
from app.config import get_settings
from app.db import admin_session, tenant_session
from app.directory import _provision_tenant
from app.logging_setup import agent_id_var, session_id_var, tenant_id_var
from app.models import AgentDef, ChannelLink
from app.orchestrator import (
    AgentDisabledError,
    UnknownAgentError,
    chat_turn,
)

log = logging.getLogger("agentcloud.channels.links")

LINK_STATUSES = ("pending", "linked", "revoked")

# base32 alphabet without ambiguous chars, uppercased, easy to type.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class ChannelValidationError(ValueError):
    """400 — bad platform / agent_id / etc."""


class ChannelNotFoundError(LookupError):
    """404 — unknown or cross-tenant link id."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_code() -> str:
    """Short, high-entropy, human-typeable pairing code."""
    n = max(4, get_settings().CHANNELS_PAIRING_CODE_BYTES) * 2
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(n))


def _link_dict(link: ChannelLink, *, include_code: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "link_id": str(link.link_id),
        "platform": link.platform,
        "agent_id": link.agent_id,
        "status": link.status,
        "platform_chat_id": link.platform_chat_id,
        "display_name": link.display_name,
        "created_at": link.created_at,
        "linked_at": link.linked_at,
    }
    if include_code:
        out["pairing_code"] = link.pairing_code
        out["expires_at"] = link.code_expires_at
    return out


def _instructions(platform: str, code: str) -> str:
    if platform == "telegram":
        return (
            f"Open the Quill Agent bot in Telegram and send:  /start {code}\n"
            f"(or just send the code {code} as a message). "
            "The code expires shortly."
        )
    return (
        f"In Google Chat, add/DM the Quill Agent app and send the code:  {code}\n"
        "The code expires shortly."
    )


# ---------------------------------------------------------------------------
# Pair (web-initiated: mint a code)
# ---------------------------------------------------------------------------


async def create_pairing(
    *, tenant_id: str, agent_id: str, platform: str
) -> dict[str, Any]:
    """Mint a single-use, expiring pairing code for (tenant, agent, platform).

    Validates the platform + that the agent exists and is enabled for the
    tenant. Returns the code + instructions (CHANNELS.md §2).
    """
    if platform not in PLATFORMS:
        raise ChannelValidationError(
            f"platform must be one of {', '.join(PLATFORMS)}"
        )
    s = get_settings()
    async with tenant_session(tenant_id) as db:
        await _provision_tenant(db, tenant_id)
        agent = (
            await db.execute(
                sa.select(AgentDef).where(
                    AgentDef.tenant_id == tenant_id,
                    AgentDef.agent_id == agent_id,
                )
            )
        ).scalar_one_or_none()
        if agent is None:
            raise UnknownAgentError(f"agent {agent_id!r} is not defined for this tenant")
        if not agent.enabled:
            raise AgentDisabledError(f"agent {agent_id!r} is disabled")

        # Collision-safe code (the partial unique index is the hard belt;
        # retry a few times on the vanishingly rare clash).
        code = _make_code()
        link_id = uuid.uuid4()
        expires = _utcnow() + timedelta(seconds=s.CHANNELS_PAIRING_TTL_SECONDS)
        db.add(
            ChannelLink(
                link_id=link_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                platform=platform,
                status="pending",
                pairing_code=code,
                code_expires_at=expires,
            )
        )
        await db.flush()
        link = (
            await db.execute(
                sa.select(ChannelLink).where(ChannelLink.link_id == link_id)
            )
        ).scalar_one()
        result = _link_dict(link, include_code=True)
    result["instructions"] = _instructions(platform, code)
    log.info(
        "pairing code created",
        extra={"extra_fields": {"link_id": str(link_id), "platform": platform}},
    )
    return result


# ---------------------------------------------------------------------------
# List / revoke (web-managed)
# ---------------------------------------------------------------------------


async def list_links(
    tenant_id: str, *, limit: int = 100, offset: int = 0
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as db:
        total = (
            await db.execute(
                sa.select(sa.func.count())
                .select_from(ChannelLink)
                .where(ChannelLink.tenant_id == tenant_id)
            )
        ).scalar_one()
        rows = (
            (
                await db.execute(
                    sa.select(ChannelLink)
                    .where(ChannelLink.tenant_id == tenant_id)
                    .order_by(ChannelLink.created_at.desc(), ChannelLink.link_id)
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return {
            "items": [_link_dict(r) for r in rows],
            "total": int(total),
            "limit": limit,
            "offset": offset,
        }


async def revoke_link(tenant_id: str, link_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as db:
        link = (
            await db.execute(
                sa.select(ChannelLink).where(
                    ChannelLink.link_id == link_id,
                    ChannelLink.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if link is None:
            raise ChannelNotFoundError("channel link not found for this tenant")
        link.status = "revoked"
        link.pairing_code = None
        link.revoked_at = _utcnow()
        await db.flush()
    return {"link_id": str(link_id), "status": "revoked"}


# ---------------------------------------------------------------------------
# Bind (bot-confirmed: redeem a code) — runs under admin scan then tenant tx
# ---------------------------------------------------------------------------


async def _find_pending_by_code(platform: str, code: str) -> tuple[str, uuid.UUID] | None:
    """Admin-scoped lookup of a valid pending link by (platform, code).

    Returns (tenant_id, link_id) or None. Expired/used codes return None (no
    enumeration oracle — the caller gives a uniform reply).
    """
    now = _utcnow()
    async with admin_session() as db:
        row = (
            await db.execute(
                sa.select(ChannelLink.tenant_id, ChannelLink.link_id).where(
                    ChannelLink.platform == platform,
                    ChannelLink.pairing_code == code,
                    ChannelLink.status == "pending",
                    sa.or_(
                        ChannelLink.code_expires_at.is_(None),
                        ChannelLink.code_expires_at > now,
                    ),
                )
            )
        ).first()
    if row is None:
        return None
    return (row[0], row[1])


async def bind_link(
    *,
    platform: str,
    code: str,
    msg: InboundMessage,
) -> dict[str, Any] | None:
    """Redeem a pairing code from the bot: bind the platform identity.

    Returns the linked-link dict on success, or None if the code is
    invalid/expired/used (the caller replies uniformly). Idempotent-ish:
    binding also clears any prior live link for this (platform, chat) so the
    routing unique index holds (re-pair to a different agent).
    """
    found = await _find_pending_by_code(platform, code)
    if found is None:
        return None
    tenant_id, link_id = found
    async with tenant_session(tenant_id) as db:
        link = (
            await db.execute(
                sa.select(ChannelLink).where(
                    ChannelLink.link_id == link_id,
                    ChannelLink.tenant_id == tenant_id,
                    ChannelLink.status == "pending",
                )
            )
        ).scalar_one_or_none()
        if link is None:
            return None  # lost a race — already bound/revoked

        # Revoke any existing live link for this (platform, chat) in THIS
        # tenant so the (platform, chat, linked) unique index holds. A chat
        # bound to a different tenant would surface as a route conflict; the
        # partial unique index is the hard belt — but per-tenant we clear our
        # own prior link first (re-pair to a new agent).
        await db.execute(
            sa.update(ChannelLink)
            .where(
                ChannelLink.tenant_id == tenant_id,
                ChannelLink.platform == platform,
                ChannelLink.platform_chat_id == msg.platform_chat_id,
                ChannelLink.status == "linked",
                ChannelLink.link_id != link_id,
            )
            .values(status="revoked", revoked_at=_utcnow())
        )

        link.status = "linked"
        link.platform_user_id = msg.platform_user_id
        link.platform_chat_id = msg.platform_chat_id
        link.display_name = msg.display_name
        link.pairing_code = None
        link.code_expires_at = None
        link.linked_at = _utcnow()
        ev = events_mod.make_event(
            tenant_id=tenant_id,
            agent_id=link.agent_id,
            type="channel.linked",
            payload={
                "link_id": str(link.link_id),
                "platform": platform,
                "platform_chat_id": msg.platform_chat_id,
                "display_name": msg.display_name,
            },
        )
        events_mod.record_events(db, [ev])
        await db.flush()
        result = _link_dict(link)
    await events_mod.emit([ev])
    log.info(
        "channel linked",
        extra={"extra_fields": {"link_id": str(link_id), "platform": platform}},
    )
    return result


# ---------------------------------------------------------------------------
# Resolve (inbound routing: platform identity → live link)
# ---------------------------------------------------------------------------


async def resolve_link(platform: str, platform_chat_id: str) -> ChannelLink | None:
    """Admin-scoped lookup of the live link for (platform, chat). None if the
    chat is not linked. Returns a detached snapshot (read-only)."""
    async with admin_session() as db:
        link = (
            await db.execute(
                sa.select(ChannelLink).where(
                    ChannelLink.platform == platform,
                    ChannelLink.platform_chat_id == platform_chat_id,
                    ChannelLink.status == "linked",
                )
            )
        ).scalar_one_or_none()
        return link


async def _set_link_session(
    tenant_id: str, link_id: uuid.UUID, session_id: uuid.UUID
) -> None:
    async with tenant_session(tenant_id) as db:
        await db.execute(
            sa.update(ChannelLink)
            .where(
                ChannelLink.link_id == link_id,
                ChannelLink.tenant_id == tenant_id,
                ChannelLink.session_id.is_(None),
            )
            .values(session_id=session_id)
        )


# ---------------------------------------------------------------------------
# Turn runner (reuse chat_turn — never fork the orchestrator)
# ---------------------------------------------------------------------------


def _is_pairing_attempt(text: str) -> str | None:
    """Extract a bare pairing code from an inbound message, if it looks like
    one. Handles Telegram '/start <code>' and a bare code."""
    t = (text or "").strip()
    if t.startswith("/start"):
        parts = t.split(None, 1)
        return parts[1].strip().upper() if len(parts) == 2 else None
    # A bare token that looks like a code (alnum, no spaces, reasonable len).
    if 4 <= len(t) <= 32 and t.replace("-", "").isalnum() and " " not in t:
        return t.upper()
    return None


def _approval_deeplink() -> str:
    base = get_settings().CHANNELS_APPROVAL_DEEPLINK_BASE.rstrip("/")
    return f"{base}/queue"


def _reply_with_approval_hint(reply: str, tool_calls: list[str]) -> str:
    """If the turn proposed an approval-gated write, append a web deep link
    (biometrics/password happen on the web, not in the bot — CHANNELS.md §7)."""
    from app.tools.quill_writes import QUILL_WRITE_TOOL_NAMES  # noqa: PLC0415

    if any(t in QUILL_WRITE_TOOL_NAMES for t in tool_calls):
        return (
            f"{reply}\n\n"
            f"⏳ This needs your approval before it happens. "
            f"Review & approve in the Quill queue: {_approval_deeplink()}"
        )
    return reply


async def handle_inbound(platform: str, msg: InboundMessage) -> str | None:
    """Process one inbound channel message. Returns the reply text (which the
    caller may deliver synchronously and/or via the adapter send), or None if
    nothing should be replied. Best-effort: never raises on a normal error —
    a malformed/edge case yields a polite reply or None.

    Flow (CHANNELS.md §2/§6):
      1. resolve the (platform, chat) → live link.
      2. if unlinked and the text is a pairing code → bind, reply confirm.
      3. if unlinked and not a code → onboarding hint.
      4. if linked → rate-limit + run one orchestrator turn on the link's
         (tenant, agent, session); append approval deep link if needed.
    """
    link = await resolve_link(platform, msg.platform_chat_id)

    # --- unlinked chat: pairing path ---------------------------------------
    if link is None:
        code = _is_pairing_attempt(msg.text)
        if code:
            bound = await bind_link(platform=platform, code=code, msg=msg)
            if bound is not None:
                return f"✓ Linked to agent “{bound['agent_id']}”. Send a message to start."
            return "That pairing code is invalid or expired. Generate a new one in Quill."
        return (
            "This chat isn't linked to a Quill agent yet. Generate a pairing "
            "code in the Quill app (Assistant → Channels) and send it here."
        )

    # --- linked chat: run a turn -------------------------------------------
    tenant_id = link.tenant_id
    agent_id = link.agent_id
    link_id = link.link_id
    link_session = link.session_id

    # Per-tenant abuse limit (B2) — shared 'chat' bucket across web + channels.
    try:
        await ratelimit_mod.enforce(tenant_id, "chat")
    except ratelimit_mod.RateLimitExceeded as exc:
        return f"You're sending messages too fast — try again in {exc.decision.retry_after_seconds}s."

    tenant_id_var.set(tenant_id)
    agent_id_var.set(agent_id)
    try:
        result = await chat_turn(
            tenant_id=tenant_id,
            agent_id=agent_id,
            message=msg.text,
            session_id=link_session,
        )
    except UnknownAgentError:
        return "That agent no longer exists. Re-pair this chat in Quill."
    except AgentDisabledError:
        return "That agent is currently disabled. Re-enable it in Quill or re-pair."
    except Exception:  # noqa: BLE001 — never crash the webhook
        log.exception("channel turn failed (link %s)", link_id)
        return "Sorry — something went wrong handling that. Please try again."

    # Persist the per-link session on first turn so the conversation has
    # continuity (only sets it when NULL, so it's stable thereafter).
    if link_session is None:
        try:
            await _set_link_session(tenant_id, link_id, result.session_id)
        except Exception:  # noqa: BLE001 — best-effort continuity
            log.warning("could not persist link session for %s", link_id)

    # channel.message event (no content — privacy; CHANNELS.md §8).
    ev = events_mod.make_event(
        tenant_id=tenant_id,
        agent_id=agent_id,
        session_id=result.session_id,
        type="channel.message",
        payload={
            "link_id": str(link_id),
            "platform": platform,
            "direction": "inbound",
            "chars": len(msg.text),
        },
    )
    session_id_var.set(str(result.session_id))
    async with tenant_session(tenant_id) as db:
        events_mod.record_events(db, [ev])
    await events_mod.emit([ev])

    return _reply_with_approval_hint(result.reply, result.tool_calls)
