"""Centralized config from environment (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )

    # --- Database ---------------------------------------------------------
    # The Secret Manager value (QUILL_DATABASE_URL) is SQLAlchemy-style
    # (postgresql+asyncpg://...). db.py normalizes whatever scheme arrives.
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./agentcloud_dev.db")
    DB_POOL_SIZE: int = Field(default=5)
    DB_MAX_OVERFLOW: int = Field(default=10)
    DB_POOL_RECYCLE_SECONDS: int = Field(default=1800)

    # --- Model provider ----------------------------------------------------
    # "anthropic" (direct API, live today) | "vertex" (config-gated; Vertex
    # Claude quota increase pending — see SPIKE_FINDINGS.md).
    MODEL_PROVIDER: str = Field(default="anthropic")
    MODEL_DEFAULT: str = Field(default="claude-fable-5")
    MODEL_CHEAP: str = Field(default="claude-haiku-4-5")
    MAX_TOKENS: int = Field(default=1024)
    MAX_TOOL_ITERATIONS: int = Field(default=6)
    MODEL_RETRY_ATTEMPTS: int = Field(default=3)
    MODEL_RETRY_BASE_DELAY: float = Field(default=1.0)

    # Vertex (Anthropic-on-Vertex). Models are only in the *global* endpoint
    # for this project (SPIKE_FINDINGS.md).
    VERTEX_PROJECT: str = Field(default="totemic-formula-467102-s9")
    VERTEX_REGION: str = Field(default="global")

    # --- Embeddings (memory subsystem) ----------------------------------
    # "gemini" (Gemini API direct, GEMINI_API_KEY — live path today) |
    # "vertex" (IAM-auth'd Vertex text embeddings; config-gated like
    # MODEL_PROVIDER) | "none" (memory falls back to text search).
    EMBEDDING_PROVIDER: str = Field(default="gemini")
    EMBEDDING_MODEL: str = Field(default="gemini-embedding-001")
    # Must match the vector(<dim>) column created by migrations.
    EMBEDDING_DIM: int = Field(default=768)
    GEMINI_API_KEY: str = Field(default="")
    EMBEDDING_TIMEOUT_SECONDS: float = Field(default=15.0)

    # --- Memory policy knobs ---------------------------------------------
    MEMORY_RECALL_TOP_K: int = Field(default=5)
    MEMORY_RECALL_MAX_CHARS: int = Field(default=2000)
    MEMORY_CONTENT_MAX_CHARS: int = Field(default=4000)

    # Optional JSON override for the pricing table, e.g.
    # {"claude-haiku-4-5": [1.0, 5.0]}  (USD per MTok in/out)
    PRICING_JSON: str = Field(default="")

    # --- Quill tool suite ---------------------------------------------------
    QUILL_API_URL: str = Field(
        default="https://quill-agents-894031978246.us-central1.run.app"
    )
    QUILL_AGENT_SECRET: str = Field(default="")
    QUILL_TOOL_TIMEOUT_SECONDS: float = Field(default=30.0)

    # --- Service-to-service auth (SEC: orchestrator public-route gate) -------
    # The orchestrator's tenant routes (/v1/agents/*) trust a caller-supplied
    # tenant_id and have no per-user auth of their own — they are meant to be
    # reached ONLY by the trusted api-bridge (which derives tenant_id
    # server-side). Because the Cloud Run service is network-public
    # (ingress=all + allUsers, matching the sibling services), we gate those
    # routes with a shared secret the bridge must send as X-Agent-Secret.
    # Falls back to QUILL_AGENT_SECRET so no new secret must be provisioned.
    # When BOTH are empty the gate is disabled (dev/tests) with a loud warning.
    SERVICE_AUTH_SECRET: str = Field(default="")

    @property
    def service_auth_secret(self) -> str:
        """Effective service-to-service secret (SERVICE_AUTH_SECRET or the
        existing QUILL_AGENT_SECRET as a fallback)."""
        return self.SERVICE_AUTH_SECRET or self.QUILL_AGENT_SECRET

    # --- Events (A3) ---------------------------------------------------
    # "inline" (in-process dispatch — local/dev/tests) | "pubsub"
    # (google-cloud-pubsub publisher; see EVENTS.md for the contract,
    # dead-letter + retry policy). Publish is always best-effort.
    EVENT_BUS: str = Field(default="inline")
    PUBSUB_PROJECT: str = Field(default="totemic-formula-467102-s9")
    EVENT_TOPIC: str = Field(default="agentcloud-events")
    EVENT_DEADLETTER_TOPIC: str = Field(default="agentcloud-events-deadletter")
    EVENT_PUBLISH_TIMEOUT_SECONDS: float = Field(default=5.0)

    # --- Sub-agent jobs (A3) ---------------------------------------------
    # "local" (in-process asyncio task — dev/tests) | "cloudrun"
    # (Cloud Run Job execution running `python -m app.jobs run <job_id>`).
    JOBS_BACKEND: str = Field(default="local")
    CLOUDRUN_JOB_NAME: str = Field(default="agentcloud-subagent")
    CLOUDRUN_JOB_REGION: str = Field(default="us-central1")
    CLOUDRUN_JOB_PROJECT: str = Field(default="totemic-formula-467102-s9")
    SUBAGENT_TASK_MAX_CHARS: int = Field(default=8000)

    # --- Scheduler (A4) ----------------------------------------------------
    # "loop" (in-process asyncio tick loop — dev/local + single-instance
    # default) | "cloudscheduler" (no in-process loop; a Cloud Scheduler HTTP
    # job POSTs /v1/internal/scheduler/tick every minute — see README).
    SCHEDULER_BACKEND: str = Field(default="loop")
    SCHEDULER_TICK_SECONDS: int = Field(default=30)
    # Max schedules claimed per tick (backpressure; the rest fire next tick).
    SCHEDULER_MAX_PER_TICK: int = Field(default=25)
    # Shared secret for POST /v1/internal/scheduler/tick (X-Agent-Secret
    # header — same internal-auth pattern as the Quill tool suite). Empty ⇒
    # the endpoint always 403s (safe default; the loop backend needs no HTTP).
    SCHEDULER_TICK_SECRET: str = Field(default="")
    SCHEDULE_MESSAGE_MAX_CHARS: int = Field(default=8000)

    # --- Approvals (A6, APPROVALS.md) ---------------------------------
    # Shared secret for POST /v1/internal/approvals/notify (X-Agent-Secret
    # header — same 403-when-unset pattern as SCHEDULER_TICK_SECRET).
    APPROVALS_NOTIFY_SECRET: str = Field(default="")
    # Reconcile sweep (belt #2): pending proposals older than this are
    # polled against GET /v1/approvals/{id} on each scheduler tick.
    APPROVALS_RECONCILE_AFTER_SECONDS: int = Field(default=120)
    APPROVALS_RECONCILE_MAX_PER_TICK: int = Field(default=25)

    # --- Agent Builder (Phase C, AGENT_BUILDER.md) -----------------------
    # Hard cap on an agent definition's system_prompt length (§4).
    SYSTEM_PROMPT_MAX_CHARS: int = Field(default=8000)

    # --- Channels (Phase D, CHANNELS.md) ---------------------------------
    # Master feature flag. False ⇒ every channel webhook + pairing endpoint
    # returns 503 (the whole feature is dark; safe default).
    CHANNELS_ENABLED: bool = Field(default=False)
    # Telegram platform bot (BotFather). Unset ⇒ telegram webhook 503.
    TELEGRAM_BOT_TOKEN: str = Field(default="")
    # setWebhook secret_token, echoed in X-Telegram-Bot-Api-Secret-Token and
    # verified per request. Unset ⇒ telegram webhook 503.
    TELEGRAM_WEBHOOK_SECRET: str = Field(default="")
    # Google Chat: in-code bearer belt for the webhook. Unset ⇒ chat 503.
    GOOGLECHAT_VERIFICATION_TOKEN: str = Field(default="")
    # SA creds JSON for the async REST send path. Unset ⇒ async send off
    # (the synchronous webhook reply still works).
    GOOGLECHAT_SERVICE_ACCOUNT_JSON: str = Field(default="")
    # App's GCP project number = the JWT audience for production verification
    # (documented Google-side hardening, CHANNELS.md §11).
    GOOGLECHAT_PROJECT_NUMBER: str = Field(default="")
    # Pairing-code lifetime + entropy (CHANNELS.md §2).
    CHANNELS_PAIRING_TTL_SECONDS: int = Field(default=900)
    CHANNELS_PAIRING_CODE_BYTES: int = Field(default=4)
    # Base URL for the web approval-queue deep link appended to bot replies
    # when a channel turn proposes an approval-gated write (CHANNELS.md §7).
    CHANNELS_APPROVAL_DEEPLINK_BASE: str = Field(
        default="https://quill-app-894031978246.us-central1.run.app"
    )
    CHANNELS_SEND_TIMEOUT_SECONDS: float = Field(default=15.0)

    # --- Budgets ------------------------------------------------------------
    DEFAULT_BUDGET_MONTHLY_USD: float = Field(default=20.0)
    # B2 tenant-level caps (LIMITS.md §1). A NULL agentcloud_tenants.
    # budget_monthly_usd defers to these: user-* personal tenants get
    # TENANT_BUDGET_DEFAULT_USD, everything else (org/smoke) gets
    # ORG_TENANT_BUDGET_USD.
    TENANT_BUDGET_DEFAULT_USD: float = Field(default=10.0)
    ORG_TENANT_BUDGET_USD: float = Field(default=100.0)

    # --- Rate limits (B2, LIMITS.md §3) ----------------------------------
    # Per-tenant fixed-window (1 min) counters in Postgres; 0 disables.
    RATE_LIMIT_PER_MIN: int = Field(default=30)  # chat turns
    RATE_LIMIT_JOBS_PER_MIN: int = Field(default=10)  # subagents + schedule creates

    # --- Per-tenant secrets (B2, SECRETS.md) ------------------------------
    # "plaintext-dev" (default — dev/tests, value stored raw, loudly named)
    # | "kms" (envelope encryption: AES-256-GCM DEK wrapped by Cloud KMS).
    SECRETS_BACKEND: str = Field(default="plaintext-dev")
    # Full KMS key resource name (SECRETS.md §5); required for kms backend.
    SECRETS_KMS_KEY: str = Field(default="")
    SECRETS_KMS_TIMEOUT_SECONDS: float = Field(default=10.0)

    # --- Ops ------------------------------------------------------------
    LOG_LEVEL: str = Field(default="INFO")
    SERVICE_NAME: str = Field(default="quill-agent-orchestrator")

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
