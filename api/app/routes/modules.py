"""Modular framework — Phase 0 routes (MODULAR_FRAMEWORK_DESIGN.md §5).

Per-workspace module enable/disable + reorder. JWT-gated; workspace resolved
server-side (personal:{user_id} | org). Reads are open to any authenticated
member; mutations are OWNER-ONLY (decision #3 — disabling can skip pipeline
steps later, so it carries real blast radius).

The response merges the static roster (canonical key set + default order) with
per-workspace overrides from module_configs. A module with no override row is
returned enabled at its roster order — so an untouched workspace looks exactly
like today (zero behavior change).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.enums import UserRole
from app.models_modules import ModuleConfig
from app.security import get_current_user

router = APIRouter(prefix="/v1/modules", tags=["modules"])


# ── Canonical roster (mirrors web/lib/modules.ts order/keys) ──────────────────
# Keys + labels + default order are the single api-side source of truth. The
# web roster owns icons/gradients; here we only need identity + order so the
# server can validate keys and compute default ordering.
MODULE_ROSTER: list[dict[str, str]] = [
    {"key": "requests", "label": "Requests"},
    {"key": "approvals", "label": "Approvals"},
    {"key": "projects", "label": "Projects"},
    {"key": "sites", "label": "Sites"},
    {"key": "contracts", "label": "Contracts"},
    {"key": "estimates", "label": "Estimates"},
    {"key": "documents", "label": "Documents"},
    {"key": "operations", "label": "Operations"},
    {"key": "sales", "label": "Sales"},
    {"key": "customers", "label": "Customers"},
    {"key": "supply-chain", "label": "Supply Chain"},
    {"key": "finance", "label": "Finance"},
    {"key": "compliance", "label": "Compliance"},
    {"key": "intelligence", "label": "Intelligence"},
    {"key": "agents", "label": "Agents"},
]
_ROSTER_KEYS = {m["key"] for m in MODULE_ROSTER}
_ROSTER_ORDER = {m["key"]: i for i, m in enumerate(MODULE_ROSTER)}


async def is_module_enabled(db: AsyncSession, workspace: str, module_key: str) -> bool:
    """Phase 2 gate (MODULAR_FRAMEWORK_DESIGN.md §3.3). True if the module is
    enabled for the workspace. FAIL-OPEN: an unknown module key, or any config
    lookup issue, returns True — we never silently skip work on ambiguity. Only
    an explicit override row with enabled=False disables it.
    """
    if module_key not in _ROSTER_KEYS:
        return True  # not a gated module — never block
    row = (
        await db.execute(
            select(ModuleConfig).where(
                ModuleConfig.workspace == workspace,
                ModuleConfig.module_key == module_key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return True  # no override → enabled by default
    return bool(row.enabled)


def _resolve_workspace(user, workspace: str) -> str:
    """Server-side workspace id. 'org' is shared; anything else is the caller's
    personal workspace. Never trust a client-supplied raw id."""
    if workspace == "org":
        return "org"
    return f"personal:{user.id}"


class ModuleConfigItem(BaseModel):
    key: str
    label: str
    enabled: bool
    sort_order: int


class ModuleConfigList(BaseModel):
    items: list[ModuleConfigItem]


class ModuleUpdate(BaseModel):
    """One module's desired state. Absent fields are left unchanged."""

    key: str = Field(min_length=1, max_length=64)
    enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)


class ModuleConfigPatch(BaseModel):
    updates: list[ModuleUpdate] = Field(min_length=1)
    workspace: str = "personal"


async def _load_overrides(db: AsyncSession, workspace: str) -> dict[str, ModuleConfig]:
    rows = (
        await db.execute(
            select(ModuleConfig).where(ModuleConfig.workspace == workspace)
        )
    ).scalars().all()
    return {r.module_key: r for r in rows}


def _merged(overrides: dict[str, ModuleConfig]) -> list[ModuleConfigItem]:
    """Roster + overrides → the effective per-workspace module list, ordered."""
    items: list[ModuleConfigItem] = []
    for m in MODULE_ROSTER:
        ov = overrides.get(m["key"])
        items.append(
            ModuleConfigItem(
                key=m["key"],
                label=m["label"],
                enabled=ov.enabled if ov is not None else True,
                sort_order=ov.sort_order if ov is not None else _ROSTER_ORDER[m["key"]],
            )
        )
    items.sort(key=lambda i: (i.sort_order, _ROSTER_ORDER[i.key]))
    return items


@router.get("", response_model=ModuleConfigList)
async def get_modules(
    workspace: str = "personal",
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ModuleConfigList:
    """Effective module config for the caller's workspace (roster + overrides).
    Open to any authenticated member (read-only)."""
    ws = _resolve_workspace(user, workspace)
    overrides = await _load_overrides(db, ws)
    return ModuleConfigList(items=_merged(overrides))


@router.patch("", response_model=ModuleConfigList)
async def patch_modules(
    body: ModuleConfigPatch,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ModuleConfigList:
    """Enable/disable and/or reorder modules for the workspace. OWNER-ONLY
    (decision #3). Upserts one override row per named module; unknown keys 400."""
    if user.role != UserRole.OWNER.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner role required")

    for u in body.updates:
        if u.key not in _ROSTER_KEYS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown module {u.key!r}")

    ws = _resolve_workspace(user, body.workspace)
    overrides = await _load_overrides(db, ws)
    now = datetime.now(UTC)

    for u in body.updates:
        row = overrides.get(u.key)
        if row is None:
            row = ModuleConfig(
                workspace=ws,
                module_key=u.key,
                enabled=True,
                sort_order=_ROSTER_ORDER[u.key],
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            overrides[u.key] = row
        if u.enabled is not None:
            row.enabled = u.enabled
        if u.sort_order is not None:
            row.sort_order = u.sort_order
        row.updated_at = now

    await db.commit()
    fresh = await _load_overrides(db, ws)
    return ModuleConfigList(items=_merged(fresh))
