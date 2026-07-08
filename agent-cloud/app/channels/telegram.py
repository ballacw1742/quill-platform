"""Telegram Bot API adapter (CHANNELS.md §4.1/§5).

Webhook auth: Telegram echoes the `setWebhook secret_token` in the
`X-Telegram-Bot-Api-Secret-Token` header; we compare it to
TELEGRAM_WEBHOOK_SECRET. Inbound `message` updates with text are handled;
everything else is ignored. Replies go out via `sendMessage`.
"""

from __future__ import annotations

import logging
from typing import Any

from app.channels.base import Adapter, InboundMessage, SendResult, get_send_client
from app.config import get_settings

log = logging.getLogger("agentcloud.channels.telegram")

SECRET_HEADER = "x-telegram-bot-api-secret-token"


class TelegramAdapter(Adapter):
    platform = "telegram"

    def configured(self) -> bool:
        s = get_settings()
        return bool(s.TELEGRAM_BOT_TOKEN and s.TELEGRAM_WEBHOOK_SECRET)

    def verify(self, headers: dict[str, str], body: dict[str, Any]) -> bool:
        secret = get_settings().TELEGRAM_WEBHOOK_SECRET
        if not secret:
            return False
        # header names are lower-cased by the caller
        got = headers.get(SECRET_HEADER, "")
        return bool(got) and got == secret

    def parse(self, body: dict[str, Any]) -> InboundMessage | None:
        if not isinstance(body, dict):
            return None
        msg = body.get("message") or body.get("edited_message")
        if not isinstance(msg, dict):
            return None
        text = msg.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        chat = msg.get("chat") or {}
        sender = msg.get("from") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return None
        display = (
            sender.get("username")
            or " ".join(
                p for p in (sender.get("first_name"), sender.get("last_name")) if p
            )
            or str(sender.get("id") or "")
        )
        return InboundMessage(
            platform=self.platform,
            platform_chat_id=str(chat_id),
            platform_user_id=str(sender.get("id") or chat_id),
            display_name=display or "telegram-user",
            text=text.strip(),
        )

    async def send(self, chat_id: str, text: str) -> SendResult:
        s = get_settings()
        if not s.TELEGRAM_BOT_TOKEN:
            return SendResult(ok=False, detail="TELEGRAM_BOT_TOKEN unset")
        url = f"https://api.telegram.org/bot{s.TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            resp = await get_send_client().post(
                url, json={"chat_id": chat_id, "text": text}, headers={}
            )
        except Exception as exc:  # noqa: BLE001 — best-effort send
            log.warning("telegram send failed: %s", exc)
            return SendResult(ok=False, detail=str(exc))
        status = getattr(resp, "status_code", 200)
        ok = 200 <= int(status) < 300
        if not ok:
            log.warning("telegram sendMessage → %s", status)
        return SendResult(ok=ok, detail=f"status={status}")


ADAPTER = TelegramAdapter()
