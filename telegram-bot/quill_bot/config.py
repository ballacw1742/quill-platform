"""Bot configuration — env-driven, with sensible dev defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class BotConfig:
    # Telegram
    telegram_bot_token: str
    telegram_pairing_secret: str  # the shared secret that pairs `/start <code>` to Charles

    # Quill API
    quill_api_url: str
    quill_admin_secret: str
    quill_agent_secret: str  # for non-admin reads where service-account is enough
    quill_ws_url: str

    # Web UI (for deep links)
    quill_web_base_url: str
    deeplink_signing_secret: str
    deeplink_ttl_seconds: int = 60

    # Daily Brief
    daily_brief_chat_id: str = ""  # Charles's chat_id; populated after pairing if absent
    daily_brief_drive_path_template: str = "/Quill/briefs/{date}-daily.md"
    daily_brief_command_template: str = "quill-runtime run daily-brief --input {payload}"

    # Observability
    sentry_dsn: str = ""
    environment: str = "dev"
    log_level: str = "INFO"

    # Behavior
    fake_token_mode: bool = False  # set True in tests to skip real Telegram I/O
    poll_interval_health_s: int = 60
    reminder_lane2_4h_enabled: bool = True

    @classmethod
    def from_env(cls) -> "BotConfig":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        fake = (
            not token
            or token.startswith("fake")
            or os.environ.get("QUILL_BOT_FAKE_MODE", "").lower() in {"1", "true", "yes"}
        )
        return cls(
            telegram_bot_token=token or "fake-token-dev",
            telegram_pairing_secret=os.environ.get(
                "TELEGRAM_PAIRING_SECRET", "dev-pairing-secret-change-me"
            ),
            quill_api_url=os.environ.get("QUILL_API_URL", "http://localhost:8000"),
            quill_admin_secret=os.environ.get(
                "AGENT_SHARED_SECRET", "dev-agent-secret-change-me"
            ),
            quill_agent_secret=os.environ.get(
                "AGENT_SHARED_SECRET", "dev-agent-secret-change-me"
            ),
            quill_ws_url=os.environ.get(
                "QUILL_WS_URL",
                os.environ.get("QUILL_API_URL", "http://localhost:8000")
                .replace("http://", "ws://")
                .replace("https://", "wss://")
                + "/ws/approvals",
            ),
            quill_web_base_url=os.environ.get(
                "QUILL_WEB_BASE_URL", "http://localhost:3000"
            ),
            deeplink_signing_secret=os.environ.get(
                "DEEPLINK_SIGNING_SECRET",
                os.environ.get("ACTION_ASSERTION_SECRET", "dev-deeplink-secret"),
            ),
            deeplink_ttl_seconds=int(os.environ.get("DEEPLINK_TTL_SECONDS", "60")),
            daily_brief_chat_id=os.environ.get("DAILY_BRIEF_CHAT_ID", ""),
            sentry_dsn=os.environ.get("SENTRY_DSN_BOT", ""),
            environment=os.environ.get("ENVIRONMENT", "dev"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            fake_token_mode=fake,
        )
