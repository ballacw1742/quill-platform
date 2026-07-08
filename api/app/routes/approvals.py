"""Approval Queue routes — agent-facing + human-facing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.enums import AuthMethod, Decision
from app.models import ApprovalItem, AuditLogEntry
from app.schemas import (
    ApprovalCreate,
    ApprovalListPage,
    ApprovalOut,
    AuditEntryOut,
    CancelRequest,
    DecisionRequest,
)
from app.security import get_current_user, get_current_user_or_agent, require_agent_secret
from app.services import approvals as svc
from app.services.security import (
    used_action_jtis,
    verify_action_assertion_jwt,
)

_settings = get_settings()

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])


# ---------------------------------------------------------------------------
# Agent-facing
# ---------------------------------------------------------------------------
@router.post(
    "",
    response_model=ApprovalOut,
    status_code=status.HTTP_201_CREATED,
    summary="Agent creates a new approval item",
)
async def create_approval(
    body: ApprovalCreate,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_agent_secret),
) -> ApprovalOut:
    item = await svc.create_approval(db, payload=body.model_dump(mode="json"), actor=actor)
    await db.refresh(item, attribute_names=["records"])
    return ApprovalOut.model_validate(item)


@router.get("", response_model=ApprovalListPage, summary="List pending approvals")
async def list_approvals(
    lane: int | None = Query(default=None, ge=1, le=3),
    agent_id: str | None = None,
    workflow: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    older_than_minutes: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _actor=Depends(get_current_user_or_agent),
) -> ApprovalListPage:
    items, total = await svc.list_pending(
        db,
        lane=lane,
        agent_id=agent_id,
        workflow=workflow,
        status=status_filter,
        older_than_minutes=older_than_minutes,
        limit=limit,
        offset=offset,
    )
    out: list[ApprovalOut] = []
    for it in items:
        await db.refresh(it, attribute_names=["records"])
        out.append(ApprovalOut.model_validate(it))
    return ApprovalListPage(items=out, total=total, limit=limit, offset=offset)


@router.get("/{approval_id}", response_model=ApprovalOut, summary="Get one approval")
async def get_approval(
    approval_id: str,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(get_current_user_or_agent),
) -> ApprovalOut:
    item = await db.get(ApprovalItem, approval_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "approval not found")
    await db.refresh(item, attribute_names=["records"])
    return ApprovalOut.model_validate(item)


@router.patch(
    "/{approval_id}/cancel",
    response_model=ApprovalOut,
    summary="Agent or owner cancels its own pending approval",
)
async def cancel_approval(
    approval_id: str,
    body: CancelRequest | None = None,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_agent_secret),
) -> ApprovalOut:
    try:
        item = await svc.cancel_approval(
            db, approval_id, actor=actor, reason=(body.reason if body else None)
        )
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    await db.refresh(item, attribute_names=["records"])
    return ApprovalOut.model_validate(item)


# ---------------------------------------------------------------------------
# Human-facing
# ---------------------------------------------------------------------------
@router.post(
    "/{approval_id}/decide",
    response_model=ApprovalOut,
    summary="Approver decides on a pending item",
)
async def decide(
    approval_id: str,
    body: DecisionRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ApprovalOut:
    # Sprint 2.2: require a fresh passkey-minted action assertion JWT,
    # bound to the *exact* decision the user is about to commit. The dev
    # fallback path (any non-empty token) is preserved only when
    # DEV_AUTH_FALLBACK is on, so the existing test suite keeps passing.
    auth_method = AuthMethod.DEV_TOKEN
    looks_like_jwt = bool(body.auth_assertion) and body.auth_assertion.count(".") == 2
    if looks_like_jwt:
        expected_intent = {
            "approval_id": approval_id,
            "decision": body.decision.value
            if hasattr(body.decision, "value")
            else str(body.decision),
            "edits": body.edits,
            "rejection_reason": body.rejection_reason,
            "escalate_to_lane": body.escalate_to_lane,
        }
        # If it looks like a JWT we MUST verify it. We never silently fall
        # back when the token is JWT-shaped — that would defeat replay
        # protection.
        claims = verify_action_assertion_jwt(
            token=body.auth_assertion,
            expected_intent=expected_intent,
            expected_user_id=user.id,
        )
        jti = str(claims.get("jti", ""))
        exp = float(claims.get("exp", 0))
        if not jti or not used_action_jtis.consume(jti, exp):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "action assertion already used"
            )
        # Audit fidelity: the minted token records HOW the user re-authed
        # ("passkey" or "password"). Tokens verify identically regardless of
        # method (verify_action_assertion_jwt never inspects it); we only read
        # it here so a password-confirmed approval is forever distinguishable
        # from a passkey-signed one. Legacy tokens without the claim are
        # treated as passkey.
        auth_method = (
            AuthMethod.PASSWORD
            if claims.get("method") == "password"
            else AuthMethod.PASSKEY
        )
    elif body.auth_assertion:
        # Opaque non-JWT — only honored under the dev fallback.
        if not _settings.DEV_AUTH_FALLBACK:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "action assertion must be a passkey-issued JWT",
            )
        auth_method = AuthMethod.PASSWORD
    elif not _settings.DEV_AUTH_FALLBACK:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing auth_assertion — passkey re-auth required",
        )

    try:
        item = await svc.decide_approval(
            db,
            approval_id=approval_id,
            approver=user,
            decision=Decision(body.decision),
            edits=body.edits,
            rejection_reason=body.rejection_reason,
            auth_evidence=body.auth_assertion,
            auth_method=auth_method,
            escalate_to_lane=body.escalate_to_lane,
        )
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    await db.refresh(item, attribute_names=["records"])
    return ApprovalOut.model_validate(item)


@router.get(
    "/{approval_id}/audit",
    response_model=list[AuditEntryOut],
    summary="Audit trail for one approval",
)
async def audit_for_approval(
    approval_id: str,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(get_current_user_or_agent),
) -> list[AuditEntryOut]:
    item = await db.get(ApprovalItem, approval_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "approval not found")
    res = await db.execute(
        select(AuditLogEntry)
        .where(AuditLogEntry.approval_item_id == approval_id)
        .order_by(AuditLogEntry.id.asc())
    )
    return [AuditEntryOut.model_validate(e) for e in res.scalars().all()]
