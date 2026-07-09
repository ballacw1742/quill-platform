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
import re

from app.models_modules import CustomModule, ModuleConfig
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

# ── Fixed sub-feature catalog (Phase 1, decision #2 = fixed list) ─────────────
# Each entry: feature_key -> human label. Only modules with meaningful
# separable parts are listed; modules absent here simply have no sub-features.
# Disabling a feature will skip that specific part of the module's pipeline.
MODULE_FEATURES: dict[str, list[dict[str, str]]] = {
    "contracts": [
        {"key": "change_orders", "label": "Change orders"},
        {"key": "clause_library", "label": "Clause library"},
        {"key": "templates", "label": "Templates"},
        {"key": "e_sign", "label": "E-signature"},
    ],
    "projects": [
        {"key": "rfi", "label": "RFIs"},
        {"key": "schedule", "label": "Schedule monitoring"},
        {"key": "submittals", "label": "Submittals"},
        {"key": "owner_reports", "label": "Owner reports"},
    ],
    "estimates": [
        {"key": "takeoff", "label": "Takeoff"},
        {"key": "unit_pricing", "label": "Unit pricing"},
        {"key": "bid_export", "label": "Bid export"},
    ],
    "sites": [
        {"key": "evaluation", "label": "Evaluation"},
        {"key": "research", "label": "Research"},
        {"key": "scoring", "label": "Scoring"},
    ],
    "supply-chain": [
        {"key": "procurement", "label": "Procurement"},
        {"key": "vendors", "label": "Vendors"},
        {"key": "equipment", "label": "Equipment tracking"},
    ],
    "operations": [
        {"key": "incidents", "label": "Incidents"},
        {"key": "uptime", "label": "Uptime / PUE"},
        {"key": "field_reports", "label": "Field reports"},
    ],
}
_FEATURE_KEYS: dict[str, set[str]] = {
    mod: {f["key"] for f in feats} for mod, feats in MODULE_FEATURES.items()
}


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


async def is_feature_enabled(
    db: AsyncSession, workspace: str, module_key: str, feature_key: str
) -> bool:
    """Phase 1 sub-feature gate. True unless BOTH the module is enabled AND the
    specific feature is explicitly disabled. FAIL-OPEN on any ambiguity
    (unknown module/feature, no row, missing key = enabled).
    """
    if module_key not in _ROSTER_KEYS:
        return True
    row = (
        await db.execute(
            select(ModuleConfig).where(
                ModuleConfig.workspace == workspace,
                ModuleConfig.module_key == module_key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return True
    if not row.enabled:
        return False  # whole module off → feature is off too
    feats = row.features or {}
    return bool(feats.get(feature_key, True))


def _resolve_workspace(user, workspace: str) -> str:
    """Server-side workspace id. 'org' is shared; anything else is the caller's
    personal workspace. Never trust a client-supplied raw id."""
    if workspace == "org":
        return "org"
    return f"personal:{user.id}"


class ModuleFeatureItem(BaseModel):
    key: str
    label: str
    enabled: bool


_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


class ModuleConfigItem(BaseModel):
    key: str
    label: str
    enabled: bool
    sort_order: int
    features: list[ModuleFeatureItem] = Field(default_factory=list)
    # Phase 3: presentation + provenance for the home grid. Builtins carry
    # None for href/gradient/icon (web owns those); customs carry their own.
    custom: bool = False
    href: str | None = None
    gradient: str | None = None
    icon: str | None = None


class ModuleConfigList(BaseModel):
    items: list[ModuleConfigItem]


class ModuleUpdate(BaseModel):
    """One module's desired state. Absent fields are left unchanged.
    `features` is a partial {feature_key: enabled} map merged into the row."""

    key: str = Field(min_length=1, max_length=64)
    enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)
    features: dict[str, bool] | None = None


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


def _feature_items(module_key: str, ov: ModuleConfig | None) -> list[ModuleFeatureItem]:
    """Fixed feature catalog for a module, with each feature's effective enabled
    state (override dict wins; missing key = enabled)."""
    catalog = MODULE_FEATURES.get(module_key, [])
    saved = (ov.features if ov is not None else None) or {}
    return [
        ModuleFeatureItem(
            key=f["key"],
            label=f["label"],
            enabled=bool(saved.get(f["key"], True)),
        )
        for f in catalog
    ]


async def _load_customs(db: AsyncSession, workspace: str) -> list[CustomModule]:
    return list(
        (
            await db.execute(
                select(CustomModule).where(CustomModule.workspace == workspace)
            )
        )
        .scalars()
        .all()
    )


def _custom_feature_items(
    cm: CustomModule, ov: ModuleConfig | None
) -> list[ModuleFeatureItem]:
    saved = (ov.features if ov is not None else None) or {}
    return [
        ModuleFeatureItem(
            key=f["key"], label=f["label"], enabled=bool(saved.get(f["key"], True))
        )
        for f in (cm.features or [])
    ]


def _merged(
    overrides: dict[str, ModuleConfig], customs: list[CustomModule] | None = None
) -> list[ModuleConfigItem]:
    """Roster + custom modules + overrides → effective per-workspace list.
    Builtins keep roster order (default); customs sort after builtins unless
    an override pins them earlier."""
    items: list[ModuleConfigItem] = []
    for m in MODULE_ROSTER:
        ov = overrides.get(m["key"])
        items.append(
            ModuleConfigItem(
                key=m["key"],
                label=m["label"],
                enabled=ov.enabled if ov is not None else True,
                sort_order=ov.sort_order if ov is not None else _ROSTER_ORDER[m["key"]],
                features=_feature_items(m["key"], ov),
            )
        )
    base_order: dict[str, int] = dict(_ROSTER_ORDER)
    for idx, cm in enumerate(customs or []):
        ov = overrides.get(cm.module_key)
        # Customs default to sorting after all builtins, in creation order.
        default_order = len(MODULE_ROSTER) + idx
        base_order[cm.module_key] = default_order
        items.append(
            ModuleConfigItem(
                key=cm.module_key,
                label=cm.label,
                enabled=ov.enabled if ov is not None else True,
                sort_order=ov.sort_order if ov is not None else default_order,
                features=_custom_feature_items(cm, ov),
                custom=True,
                href=cm.href,
                gradient=cm.gradient,
                icon=cm.icon,
            )
        )
    items.sort(key=lambda i: (i.sort_order, base_order.get(i.key, 999)))
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
    customs = await _load_customs(db, ws)
    return ModuleConfigList(items=_merged(overrides, customs))


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

    ws = _resolve_workspace(user, body.workspace)
    customs = await _load_customs(db, ws)
    custom_keys = {c.module_key for c in customs}
    custom_feature_keys = {
        c.module_key: {f["key"] for f in (c.features or [])} for c in customs
    }
    valid_keys = _ROSTER_KEYS | custom_keys
    for u in body.updates:
        if u.key not in valid_keys:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown module {u.key!r}")

    overrides = await _load_overrides(db, ws)
    now = datetime.now(UTC)

    # Validate any feature keys before mutating (builtin or custom feature set).
    for u in body.updates:
        if u.features:
            valid = _FEATURE_KEYS.get(u.key, set()) | custom_feature_keys.get(u.key, set())
            for fk in u.features:
                if fk not in valid:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        f"unknown feature {fk!r} for module {u.key!r}",
                    )

    for u in body.updates:
        row = overrides.get(u.key)
        if row is None:
            row = ModuleConfig(
                workspace=ws,
                module_key=u.key,
                enabled=True,
                sort_order=_ROSTER_ORDER.get(u.key, len(MODULE_ROSTER)),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            overrides[u.key] = row
        if u.enabled is not None:
            row.enabled = u.enabled
        if u.sort_order is not None:
            row.sort_order = u.sort_order
        if u.features is not None:
            merged_feats = dict(row.features or {})
            merged_feats.update(u.features)
            row.features = merged_feats
        row.updated_at = now

    await db.commit()
    fresh = await _load_overrides(db, ws)
    return ModuleConfigList(items=_merged(fresh, customs))


# ── Phase 3: Module Builder — create/edit/delete custom modules ──────────────


class CustomFeatureIn(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=80)


class CustomModuleIn(BaseModel):
    """Create a workspace-authored module (owner-only)."""

    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=80)
    href: str = Field(default="/requests", max_length=200)
    gradient: str = Field(default="from-slate-400 to-slate-600", max_length=120)
    icon: str | None = Field(default=None, max_length=60)
    features: list[CustomFeatureIn] = Field(default_factory=list)
    workspace: str = "personal"


class CustomModulePatch(BaseModel):
    """Edit an existing custom module. Absent fields unchanged."""

    label: str | None = Field(default=None, min_length=1, max_length=80)
    href: str | None = Field(default=None, max_length=200)
    gradient: str | None = Field(default=None, max_length=120)
    icon: str | None = Field(default=None, max_length=60)
    features: list[CustomFeatureIn] | None = None
    workspace: str = "personal"


def _custom_out(cm: CustomModule) -> dict:
    return {
        "key": cm.module_key,
        "label": cm.label,
        "href": cm.href,
        "gradient": cm.gradient,
        "icon": cm.icon,
        "features": cm.features or [],
        "custom": True,
    }


@router.post("/custom", status_code=status.HTTP_201_CREATED)
async def create_custom_module(
    body: CustomModuleIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Create a custom module (OWNER-ONLY). Key must be a slug, must not collide
    with a builtin roster key or an existing custom in the workspace."""
    if user.role != UserRole.OWNER.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner role required")
    if not _SLUG_RE.match(body.key):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "key must be a lowercase slug (letters/digits/internal hyphens)",
        )
    if body.key in _ROSTER_KEYS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{body.key!r} collides with a built-in module",
        )
    ws = _resolve_workspace(user, body.workspace)
    existing = (
        await db.execute(
            select(CustomModule).where(
                CustomModule.workspace == ws, CustomModule.module_key == body.key
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"module {body.key!r} already exists")
    now = datetime.now(UTC)
    cm = CustomModule(
        workspace=ws,
        module_key=body.key,
        label=body.label,
        href=body.href,
        gradient=body.gradient,
        icon=body.icon,
        features=[{"key": f.key, "label": f.label} for f in body.features],
        created_at=now,
        updated_at=now,
    )
    db.add(cm)
    await db.commit()
    await db.refresh(cm)
    return _custom_out(cm)


@router.patch("/custom/{module_key}")
async def edit_custom_module(
    module_key: str,
    body: CustomModulePatch,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Edit a custom module's presentation/features (OWNER-ONLY). 404 unknown."""
    if user.role != UserRole.OWNER.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner role required")
    ws = _resolve_workspace(user, body.workspace)
    cm = (
        await db.execute(
            select(CustomModule).where(
                CustomModule.workspace == ws, CustomModule.module_key == module_key
            )
        )
    ).scalar_one_or_none()
    if cm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "custom module not found")
    if body.label is not None:
        cm.label = body.label
    if body.href is not None:
        cm.href = body.href
    if body.gradient is not None:
        cm.gradient = body.gradient
    if body.icon is not None:
        cm.icon = body.icon
    if body.features is not None:
        cm.features = [{"key": f.key, "label": f.label} for f in body.features]
    cm.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(cm)
    return _custom_out(cm)


@router.delete("/custom/{module_key}")
async def delete_custom_module(
    module_key: str,
    workspace: str = "personal",
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete a custom module (OWNER-ONLY). Also removes any config override
    row for it so no orphan config lingers. 404 unknown."""
    if user.role != UserRole.OWNER.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner role required")
    ws = _resolve_workspace(user, workspace)
    cm = (
        await db.execute(
            select(CustomModule).where(
                CustomModule.workspace == ws, CustomModule.module_key == module_key
            )
        )
    ).scalar_one_or_none()
    if cm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "custom module not found")
    await db.delete(cm)
    # Best-effort cleanup of any override row.
    ov = (
        await db.execute(
            select(ModuleConfig).where(
                ModuleConfig.workspace == ws, ModuleConfig.module_key == module_key
            )
        )
    ).scalar_one_or_none()
    if ov is not None:
        await db.delete(ov)
    await db.commit()
    return {"key": module_key, "deleted": True}
