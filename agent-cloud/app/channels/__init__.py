"""External channel adapters (Telegram + Google Chat) + pairing flow.

Contract: agent-cloud/CHANNELS.md (read it before touching channel code).

Layout:
  links.py       — pairing/link lifecycle (pair/bind/list/revoke) + inbound
                   identity->tenant/agent resolution + the shared turn runner.
  base.py        — Adapter protocol + a mockable HTTP send-client factory.
  telegram.py    — Telegram Bot API adapter (webhook parse + sendMessage).
  googlechat.py  — Google Chat adapter (event parse + sync reply / async send).

Channel adapters feed the SAME orchestrator turn loop as web chat
(app/orchestrator.py:stream_turn / chat_turn); they never fork it.
"""

from __future__ import annotations


def get_adapter(platform: str):
    """Return the singleton Adapter for a platform, or None if unknown."""
    if platform == "telegram":
        from app.channels.telegram import ADAPTER  # noqa: PLC0415

        return ADAPTER
    if platform == "googlechat":
        from app.channels.googlechat import ADAPTER  # noqa: PLC0415

        return ADAPTER
    return None
