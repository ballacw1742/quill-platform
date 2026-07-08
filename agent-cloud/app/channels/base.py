"""Base channel-adapter protocol + a mockable outbound-send client factory.

An Adapter turns a raw platform webhook body into a normalized
`InboundMessage` (or None when the update isn't a text message we handle),
and can `send(chat_id, text)` a reply out-of-band. The happy-path reply for
Google Chat is the synchronous webhook response, so `send` is only used for
out-of-band messages there (CHANNELS.md §5); Telegram always uses `send`.

The HTTP send clients are created through a module-level factory so tests
inject a mock and no network happens (CONTRIBUTING_AGENTS §5/§8).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

PLATFORMS = ("telegram", "googlechat")


@dataclass
class InboundMessage:
    """Normalized inbound channel message (adapter-agnostic)."""

    platform: str
    platform_chat_id: str  # routing key (Telegram chat.id / Chat space.name)
    platform_user_id: str  # sender id
    display_name: str  # best-effort human label
    text: str  # message body (mentions stripped)


@dataclass
class SendResult:
    ok: bool
    detail: str = ""


class SendClient(Protocol):
    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
        ...


class _HttpxSendClient:
    """Thin httpx wrapper; the only production send transport."""

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]):
        import httpx  # noqa: PLC0415

        from app.config import get_settings  # noqa: PLC0415

        timeout = get_settings().CHANNELS_SEND_TIMEOUT_SECONDS
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.post(url, json=json, headers=headers)


# Injectable factory (tests replace it via set_send_client).
_send_client_factory: Callable[[], SendClient] = _HttpxSendClient


def get_send_client() -> SendClient:
    return _send_client_factory()


def set_send_client(factory: Callable[[], SendClient] | None) -> None:
    """Test hook — pin/reset the outbound HTTP send client factory."""
    global _send_client_factory
    _send_client_factory = factory or _HttpxSendClient


class Adapter(Protocol):
    platform: str

    def configured(self) -> bool:
        """True iff this platform's required config (token/secret) is present."""
        ...

    def verify(self, headers: dict[str, str], body: dict[str, Any]) -> bool:
        """Per-platform webhook signature/secret verification."""
        ...

    def parse(self, body: dict[str, Any]) -> InboundMessage | None:
        """Normalize a webhook body → InboundMessage, or None to ignore."""
        ...

    async def send(self, chat_id: str, text: str) -> SendResult:
        """Out-of-band reply (Telegram sendMessage / Chat async REST)."""
        ...
