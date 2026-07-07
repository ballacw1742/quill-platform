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

    # --- Budgets ------------------------------------------------------------
    DEFAULT_BUDGET_MONTHLY_USD: float = Field(default=20.0)

    # --- Ops ------------------------------------------------------------
    LOG_LEVEL: str = Field(default="INFO")
    SERVICE_NAME: str = Field(default="quill-agent-orchestrator")

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
