"""Centralized config. Pulled from environment via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./quill_dev.db",
        description="Async SQLAlchemy URL.",
    )
    DATABASE_URL_SYNC: str = Field(
        default="sqlite:///./quill_dev.db",
        description="Sync SQLAlchemy URL (used by alembic).",
    )

    # Auth / signing
    SECRET_KEY: str = Field(default="dev-secret-change-me")
    AGENT_SHARED_SECRET: str = Field(default="dev-agent-secret-change-me")

    # WebAuthn / passkey config (Sprint 2.2)
    WEBAUTHN_RP_ID: str = Field(default="localhost")
    WEBAUTHN_RP_NAME: str = Field(default="Quill")
    WEBAUTHN_ORIGIN: str = Field(default="http://localhost:3000")
    # Comma-separated allow-list of origins; defaults to WEBAUTHN_ORIGIN.
    WEBAUTHN_EXTRA_ORIGINS: str = Field(default="")
    # Separate signing key for the short-lived approval action assertion.
    ACTION_ASSERTION_SECRET: str = Field(default="dev-action-assertion-change-me")
    ACTION_ASSERTION_TTL_SECONDS: int = Field(default=60)
    # Keep email/password login as a developer fallback (default off in prod).
    DEV_AUTH_FALLBACK: bool = Field(default=True)
    SESSION_TTL_HOURS: int = Field(default=4)

    # Observability
    SENTRY_DSN: str = Field(default="")
    LOG_LEVEL: str = Field(default="INFO")

    # CORS
    CORS_ORIGINS: str = Field(default="http://localhost:3000,http://localhost:5173")

    # Notifications
    TELEGRAM_NOTIFY_CHAT_ID: str = Field(default="")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def webauthn_origins(self) -> list[str]:
        extras = [o.strip() for o in self.WEBAUTHN_EXTRA_ORIGINS.split(",") if o.strip()]
        return [self.WEBAUTHN_ORIGIN, *extras]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
