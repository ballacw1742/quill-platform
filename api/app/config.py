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
    # Sprint 5.5 (G13 / KNOWN_ISSUES #9) — open self-registration is disabled by
    # default. When false, POST /v1/auth/register requires an owner bearer token
    # (owner provisions/invites accounts). Set true only for local dev/demo seeding.
    ALLOW_SELF_REGISTER: bool = Field(default=False)
    SESSION_TTL_HOURS: int = Field(default=4)

    # Observability
    SENTRY_DSN: str = Field(default="")
    LOG_LEVEL: str = Field(default="INFO")

    # CORS
    CORS_ORIGINS: str = Field(default="http://localhost:3000,http://localhost:5173")

    # Notifications
    TELEGRAM_NOTIFY_CHAT_ID: str = Field(default="")

    # External service URLs
    DATASITE_URL: str = Field(
        default="https://datasite-agents-894031978246.us-central1.run.app",
        description="DataSite Intelligence Cloud Run service URL.",
    )
    INTERNAL_API_URL: str = Field(
        default="https://quill-adk-agents-894031978246.us-central1.run.app",
        description="Quill ADK agents Cloud Run service URL.",
    )

    # Agent Cloud bridge (Sprint A5 — agent-cloud/WEBCHAT.md)
    AGENTCLOUD_URL: str = Field(
        default="http://localhost:8010",
        description="quill-agent-orchestrator base URL (Cloud Run URL in prod).",
    )
    AGENTCLOUD_TENANT_ID: str = Field(
        default="quill-main",
        description="This deployment's agent-cloud tenant id (WEBCHAT.md §1). "
        "Never taken from the client. smoke- prefix seeds cheap-tier models.",
    )
    AGENTCLOUD_TIMEOUT_SECONDS: float = Field(
        default=120.0,
        description="Per-request budget for non-stream agent-cloud calls.",
    )
    # Sprint B1 — agent-cloud/TENANCY.md §2. Hard cap on the best-effort
    # signup-time tenant provisioning call (registration is delayed at most
    # this long when agent-cloud is down, and never fails because of it).
    AGENTCLOUD_PROVISION_TIMEOUT_SECONDS: float = Field(
        default=3.0,
        description="Timeout for the best-effort signup tenant provisioning hook.",
    )
    # Sprint A6 — agent-cloud/APPROVALS.md §6. Shared secret for the
    # best-effort resolution notify POST to agent-cloud
    # /v1/internal/approvals/notify. Empty ⇒ notify disabled (the agent-cloud
    # reconcile sweep still closes the loop by polling).
    AGENTCLOUD_NOTIFY_SECRET: str = Field(
        default="",
        description="Shared secret for agent-cloud approvals resolution notify.",
    )
    # SEC: the orchestrator's tenant routes (/v1/agents/*) are gated behind a
    # shared X-Agent-Secret because the service is network-public. The bridge
    # is the ONLY legitimate caller, so it attaches this on every forwarded
    # request. Set to the same value as the orchestrator's
    # SERVICE_AUTH_SECRET / QUILL_AGENT_SECRET. Empty in dev/tests (gate off).
    AGENTCLOUD_SERVICE_SECRET: str = Field(
        default="",
        description="X-Agent-Secret sent to the orchestrator's tenant routes.",
    )

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

    # Google Drive / Docs / Sheets authoring (Phase F/H — api-side pipeline)
    # -----------------------------------------------------------------
    # Master flag. False (default) ⇒ Drive authoring is skipped; deliverable
    # stays as a text/local record. Flip to True only once the service account
    # + folder are configured on the quill-agents Cloud Run service.
    DRIVE_ENABLED: bool = Field(default=False)
    # Full JSON key of the Drive service account (single-line string).
    # Mirrors DRIVE_SERVICE_ACCOUNT_JSON in agent-cloud's config exactly.
    DRIVE_SERVICE_ACCOUNT_JSON: str = Field(default="")
    # Drive folder ID where new Docs/Sheets are created.
    # Leave empty to create in the service account's My Drive root.
    DRIVE_FOLDER_ID: str = Field(default="")

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
