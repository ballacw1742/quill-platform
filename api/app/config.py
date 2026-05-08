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

    # Documents service (Phase D.1)
    DOCUMENTS_BLOB_PATH: str = Field(
        default="./_local_documents",
        description="Local fallback dir for document markdown bodies (MinIO key prefix on prod).",
    )
    DOCUMENTS_DRIVE_ENABLED: bool = Field(
        default=False,
        description="When True, kick off async `gog drive upload` after publishing a document.",
    )

    # Audit log resilience (Sprint 2.3)
    B2_KEY_ID: str = Field(default="", description="Backblaze B2 application key ID.")
    B2_APPLICATION_KEY: str = Field(default="", description="Backblaze B2 application key secret.")
    B2_BUCKET: str = Field(default="quill-audit", description="B2 bucket holding the audit mirror.")
    B2_OBJECT_LOCK_YEARS: int = Field(default=7, description="Object Lock compliance retention (years).")
    AUDIT_MIRROR_LOCAL_PATH: str = Field(
        default="./_local_audit_mirror",
        description="Local fallback dir when B2 creds are absent.",
    )
    AUDIT_MIRROR_MAX_RETRIES: int = Field(default=5, description="Max retries before paging.")
    AUDIT_MIRROR_DRAIN_INTERVAL_SECONDS: float = Field(default=2.0)
    # Sprint-4 fix #8: when True the audit-mirror worker tries to claim each
    # entry hash in audit_mirror_claims before writing to B2. Default off so
    # single-replica + sqlite dev keeps working with no migration churn.
    AUDIT_MIRROR_CLAIM_IN_POSTGRES: bool = Field(default=False)
    AUDIT_VERIFY_SCHEDULE_CRON: str = Field(
        default="0 2 * * *",
        description="Nightly verify schedule (informational; OS cron drives the actual run).",
    )
    AUDIT_FREEZE_FLAG_PATH: str = Field(
        default="./_audit_freeze.flag",
        description="Touch-file feature flag: presence freezes audit writes.",
    )

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
