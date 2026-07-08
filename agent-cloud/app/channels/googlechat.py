"""Google Chat adapter (CHANNELS.md §4.2/§5).

Webhook auth: Google Chat signs each request with a Google-issued Bearer JWT
(audience = the app's project number). Full JWT verification requires
Google's public certs (a live/ops dependency documented in CHANNELS.md §11);
the in-code belt verifies a shared bearer token
(GOOGLECHAT_VERIFICATION_TOKEN). Inbound `MESSAGE` events are handled.

Happy-path replies use the SYNCHRONOUS webhook response (the webhook returns
{"text": ...}, which Google posts into the space), so no async send
credential is needed for the common case. The async REST send path
(spaces.messages.create) is implemented for out-of-band messages and gated
on GOOGLECHAT_SERVICE_ACCOUNT_JSON.
"""

from __future__ import annotations

import logging
from typing import Any

from app.channels.base import Adapter, InboundMessage, SendResult, get_send_client
from app.config import get_settings

log = logging.getLogger("agentcloud.channels.googlechat")

AUTH_HEADER = "authorization"


def _strip_mention(text: str, annotations: list[Any] | None) -> str:
    """Remove a leading @-app mention from the message text."""
    if not text:
        return ""
    # Google Chat gives USER_MENTION annotations; simplest robust strip is to
    # drop a leading token that looks like a mention (starts with '@').
    stripped = text.strip()
    if stripped.startswith("@"):
        parts = stripped.split(None, 1)
        stripped = parts[1] if len(parts) == 2 else ""
    return stripped.strip()


class GoogleChatAdapter(Adapter):
    platform = "googlechat"

    def configured(self) -> bool:
        # The webhook + synchronous reply only need the verification token.
        # The async send path additionally needs the service-account JSON,
        # but the happy path (sync reply) works without it.
        return bool(get_settings().GOOGLECHAT_VERIFICATION_TOKEN)

    def verify(self, headers: dict[str, str], body: dict[str, Any]) -> bool:
        token = get_settings().GOOGLECHAT_VERIFICATION_TOKEN
        if not token:
            return False
        auth = headers.get(AUTH_HEADER, "")
        # Accept "Bearer <token>" or a bare token.
        if auth.lower().startswith("bearer "):
            auth = auth[7:]
        return bool(auth) and auth == token

    def parse(self, body: dict[str, Any]) -> InboundMessage | None:
        if not isinstance(body, dict):
            return None
        if body.get("type") != "MESSAGE":
            return None
        message = body.get("message") or {}
        space = body.get("space") or message.get("space") or {}
        user = body.get("user") or message.get("sender") or {}
        space_name = space.get("name")
        if not space_name:
            return None
        text = _strip_mention(
            str(message.get("text") or ""), message.get("annotations")
        )
        if not text:
            return None
        return InboundMessage(
            platform=self.platform,
            platform_chat_id=str(space_name),
            platform_user_id=str(user.get("name") or space_name),
            display_name=str(user.get("displayName") or "chat-user"),
            text=text,
        )

    async def send(self, chat_id: str, text: str) -> SendResult:
        """Async out-of-band send via spaces.messages.create.

        Requires GOOGLECHAT_SERVICE_ACCOUNT_JSON for a bearer token. In
        Phase D this path is implemented but only used for out-of-band
        messages; the happy-path reply uses the synchronous webhook response.
        """
        s = get_settings()
        if not s.GOOGLECHAT_SERVICE_ACCOUNT_JSON:
            return SendResult(
                ok=False, detail="GOOGLECHAT_SERVICE_ACCOUNT_JSON unset (async send disabled)"
            )
        # chat_id is the space resource name, e.g. "spaces/AAAA".
        url = f"https://chat.googleapis.com/v1/{chat_id}/messages"
        try:
            token = await self._access_token()
        except Exception as exc:  # noqa: BLE001
            log.warning("google chat token mint failed: %s", exc)
            return SendResult(ok=False, detail=str(exc))
        try:
            resp = await get_send_client().post(
                url,
                json={"text": text},
                headers={"Authorization": f"Bearer {token}"},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("google chat send failed: %s", exc)
            return SendResult(ok=False, detail=str(exc))
        status = getattr(resp, "status_code", 200)
        ok = 200 <= int(status) < 300
        return SendResult(ok=ok, detail=f"status={status}")

    async def _access_token(self) -> str:  # pragma: no cover — exercised in prod
        """Mint an OAuth access token from the service-account JSON.

        Kept isolated so tests that exercise send() mock get_send_client and
        never reach here (the sync-reply happy path is the tested one).
        """
        import json  # noqa: PLC0415

        from google.auth.transport.requests import Request  # noqa: PLC0415
        from google.oauth2 import service_account  # noqa: PLC0415

        info = json.loads(get_settings().GOOGLECHAT_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/chat.bot"]
        )
        creds.refresh(Request())
        return creds.token


ADAPTER = GoogleChatAdapter()
