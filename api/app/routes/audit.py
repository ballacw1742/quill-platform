"""Audit log routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import AuditLogEntry
from app.schemas import AuditEntryOut, AuditVerifyResult
from app.services import audit as audit_svc

router = APIRouter(prefix="/v1/audit", tags=["audit"])


@router.get("/recent", response_model=list[AuditEntryOut])
async def recent_audit(
    limit: int = Query(default=100, ge=1, le=500),
    event_type: str | None = None,
    actor: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[AuditEntryOut]:
    stmt = select(AuditLogEntry).order_by(AuditLogEntry.id.desc()).limit(limit)
    if event_type:
        stmt = stmt.where(AuditLogEntry.event_type == event_type)
    if actor:
        stmt = stmt.where(AuditLogEntry.actor == actor)
    res = await db.execute(stmt)
    return [AuditEntryOut.model_validate(e) for e in res.scalars().all()]


@router.get("/verify/{approval_id}", response_model=AuditVerifyResult)
async def verify_approval_chain(
    approval_id: str, db: AsyncSession = Depends(get_db)
) -> AuditVerifyResult:
    result = await audit_svc.verify_chain(db, approval_id)
    return AuditVerifyResult(**result)


@router.get("/verify", response_model=AuditVerifyResult, summary="Verify global chain")
async def verify_global_chain(db: AsyncSession = Depends(get_db)) -> AuditVerifyResult:
    result = await audit_svc.verify_chain(db, None)
    return AuditVerifyResult(**result)
