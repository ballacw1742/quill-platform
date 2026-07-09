"""ORM model for the modular framework — Phase 0 (MODULAR_FRAMEWORK_DESIGN.md).

Per-workspace module configuration: which home-screen modules are enabled and
in what order. Rows are OVERRIDES — a module with no row for a given workspace
falls back to the static roster default (enabled, roster order). This keeps the
migration purely additive: existing tenants see no change until they toggle
something.

Scope (decision #4): per-workspace to start. `workspace` is the same two-value
notion the agent-cloud bridge uses — "personal:{user_id}" or "org" — resolved
server-side from the JWT; the client never supplies a raw tenant id.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ModuleConfig(Base):
    """One module's enable/order override for one workspace.

    Absence of a row = module is enabled at its roster-default order. Presence
    lets a workspace disable a module and/or pin a custom order. `module_key`
    matches the shared web roster keys (web/lib/modules.ts).
    """

    __tablename__ = "module_configs"
    __table_args__ = (
        UniqueConstraint("workspace", "module_key", name="uq_module_configs_ws_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # "personal:{user_id}" | "org" — resolved server-side, never client-supplied.
    workspace: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    module_key: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Lower sorts first. Nullable-free; defaults to the roster order on seed.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
