"""Runtime-side notification + telemetry hooks (Sprint 2.4)."""

from runtime.notifications.sentry import (
    capture_exception,
    capture_message,
    init,
    tag_agent,
    tag_approval,
    tag_run,
)

__all__ = [
    "capture_exception",
    "capture_message",
    "init",
    "tag_agent",
    "tag_approval",
    "tag_run",
]
