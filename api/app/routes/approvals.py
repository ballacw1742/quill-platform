"""Approval Queue routes — agent-facing + human-facing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.security import get_current_user, require_agent_secret
from app.services import approvals as svc

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
async def get_approval(approval_id: str, db: AsyncSession = Depends(get_db)) -> ApprovalOut:
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
    # Sprint 1: auth_assertion is just stamped as evidence; Sprint 2 verifies WebAuthn.
    auth_method = AuthMethod.DEV_TOKEN
    if body.auth_assertion:
        auth_method = AuthMethod.PASSWORD
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
    approval_id: str, db: AsyncSession = Depends(get_db)
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
