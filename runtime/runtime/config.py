"""Env-driven runtime configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import structlog
from dotenv import load_dotenv

# Load .env from CWD and from the runtime package root if present.
load_dotenv()

# Default to repo-relative location for the prompts repo.
_DEFAULT_PROMPTS = Path(
    "/Users/charlesmitchell/.openclaw/workspace/agentic-pmo-prompts"
)


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration pulled from the environment."""

    prompts_repo_path: Path = field(default_factory=lambda: _DEFAULT_PROMPTS)
    queue_api_url: str = "http://localhost:8000"
    agent_shared_secret: str = "dev-agent-secret-change-me"
    anthropic_api_key: str | None = None
    default_model_override: str | None = None
    on_prem_inference_url: str | None = None
    log_level: str = "INFO"
    request_timeout_s: float = 60.0

    @classmethod
    def from_env(cls) -> Config:
        prompts = os.environ.get("PROMPTS_REPO_PATH")
        prompts_path = Path(prompts) if prompts else _DEFAULT_PROMPTS
        return cls(
            prompts_repo_path=prompts_path,
            queue_api_url=os.environ.get("QUEUE_API_URL", "http://localhost:8000").rstrip("/"),
            agent_shared_secret=os.environ.get(
                "AGENT_SHARED_SECRET", "dev-agent-secret-change-me"
            ),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            default_model_override=os.environ.get("DEFAULT_MODEL_OVERRIDE") or None,
            on_prem_inference_url=os.environ.get("ON_PREM_INFERENCE_URL") or None,
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            request_timeout_s=float(os.environ.get("RUNTIME_REQUEST_TIMEOUT_S", "60")),
        )

    def configure_logging(self) -> None:
        """Wire up structlog at the configured level. Idempotent."""
        level = getattr(logging, self.log_level, logging.INFO)
        logging.basicConfig(
            level=level,
            format="%(message)s",
        )
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(level),
            processors=[
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer(),
            ],
            cache_logger_on_first_use=True,
        )


@lru_cache(maxsize=1)
def get_config() -> Config:
    cfg = Config.from_env()
    cfg.configure_logging()
    return cfg


__all__ = ["Config", "get_config"]
