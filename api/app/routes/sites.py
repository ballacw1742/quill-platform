"""
Quill Sites routes — proxies to DataSite Intelligence Cloud Run service.
Surfaces site evaluation functionality within the Quill platform.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import httpx

from app.db import get_db
from app.enums import ApprovalStatus, Lane
from app.models import ApprovalItem
from app.models_projects import Project
from app.models_sites import SiteDriveIntake
from app.security import get_current_user
from app.services import approvals as approvals_svc
from app.services import audit as audit_svc
from app.services import site_drive_intake as intake_svc
from app.services.approvals import SITE_ADVANCE_WORKFLOW

router = APIRouter(prefix="/v1/sites", tags=["sites"])

DATASITE_URL = os.environ.get("DATASITE_URL", "https://datasite-agents-894031978246.us-central1.run.app")


async def _datasite_request(method: str, path: str, **kwargs):
    """Make a request to the DataSite service."""
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await getattr(client, method)(f"{DATASITE_URL}{path}", **kwargs)
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
        return resp.json()


@router.get("")
async def list_sites(
    status: str = None,
    user=Depends(get_current_user),
):
    """List all site evaluations."""
    params = {}
    if status:
        params["status"] = status
    return await _datasite_request("get", "/sites", params=params)


@router.get("/{site_id}")
async def get_site(
    site_id: str,
    user=Depends(get_current_user),
):
    """Get a single site evaluation."""
    return await _datasite_request("get", f"/sites/{site_id}")


@router.post("")
async def create_site(
    body: dict,
    user=Depends(get_current_user),
):
    """Create a new site evaluation."""
    return await _datasite_request("post", "/sites", json=body)


@router.post("/{site_id}/run")
async def run_site_evaluation(
    site_id: str,
    user=Depends(get_current_user),
):
    """Trigger the evaluation pipeline for a site."""
    return await _datasite_request("post", f"/sites/{site_id}/run", json={})


# ---------------------------------------------------------------------------
# Document upload endpoints (Sprint DC.3)
# ---------------------------------------------------------------------------

class DriveDocumentIn(BaseModel):
    drive_folder_url: str


@router.post("/{site_id}/documents", summary="Upload supporting documents for a site")
async def upload_site_documents(
    site_id: str,
    files: list[UploadFile] = File(...),
    user=Depends(get_current_user),
):
    """Upload one or more PDF/DOCX supporting documents for a site evaluation.

    Attempts to forward files to DataSite's document upload endpoint.
    Returns a summary of what was uploaded regardless of whether DataSite
    accepted them (DataSite document endpoints are optional — the core
    evaluation pipeline can run without them).
    """
    results = []
    for f in files:
        content = await f.read()
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{DATASITE_URL}/sites/{site_id}/documents",
                    files=[("file", (f.filename, content, f.content_type or "application/octet-stream"))],
                )
                if resp.status_code < 400:
                    results.append({"filename": f.filename, "status": "uploaded", "detail": resp.json()})
                else:
                    # Non-fatal — log and continue
                    results.append({"filename": f.filename, "status": "queued", "detail": f"DataSite returned {resp.status_code}"})
        except Exception as exc:  # noqa: BLE001
            # DataSite may not have this endpoint yet; treat as queued
            results.append({"filename": f.filename, "status": "queued", "detail": str(exc)[:200]})
    return {"site_id": site_id, "documents": results}


def _intake_out(intake: SiteDriveIntake) -> dict:
    return {
        "intake_id": intake.id,
        "site_id": intake.site_id,
        "drive_folder_url": intake.folder_url,
        "status": intake.status,
        "error": intake.error,
        "documents": intake.documents or [],
        "created_at": intake.created_at.isoformat() if intake.created_at else None,
    }


@router.post("/{site_id}/documents/drive", summary="Import documents from a Google Drive folder")
async def attach_site_drive_folder(
    site_id: str,
    body: DriveDocumentIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import a Google Drive folder's documents into a site evaluation.

    Sprint 2: this is an honest, synchronous intake. The folder is listed
    and downloaded via the local `gog` Drive identity, each supported file
    is uploaded to DataSite, and the DataSite document analyst is run.
    The response carries a real per-document status (indexed / uploaded /
    skipped / failed) — never a fake "queued" success.
    """
    # Confirm the site exists before doing any Drive work (404 passthrough).
    await _datasite_request("get", f"/sites/{site_id}")

    if not intake_svc.parse_folder_id(body.drive_folder_url):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"not a recognizable Google Drive folder URL: {body.drive_folder_url}",
        )

    result = await intake_svc.run_intake(site_id, body.drive_folder_url)

    intake = SiteDriveIntake(
        site_id=site_id,
        folder_url=body.drive_folder_url,
        requested_by=str(user.id),
        status=result["status"],
        error=result.get("error"),
        documents=result["documents"],
    )
    db.add(intake)
    await db.flush()
    await audit_svc.record_event_with_mirror(
        db,
        event_type="site.drive_intake",
        actor=str(user.id),
        approval_item_id=None,
        payload={
            "site_id": site_id,
            "intake_id": intake.id,
            "folder_url": body.drive_folder_url,
            "status": result["status"],
            "documents": [
                {"filename": d["filename"], "status": d["status"]}
                for d in result["documents"]
            ],
        },
    )
    await db.commit()
    await db.refresh(intake)
    return _intake_out(intake)


@router.get("/{site_id}/documents/drive", summary="Latest Drive intake status for a site")
async def get_site_drive_intake(
    site_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent Drive intake run for this site (or status none)."""
    res = await db.execute(
        select(SiteDriveIntake)
        .where(SiteDriveIntake.site_id == site_id)
        .order_by(SiteDriveIntake.created_at.desc())
        .limit(1)
    )
    intake = res.scalars().first()
    if intake is None:
        return {"site_id": site_id, "status": "none", "documents": []}
    return _intake_out(intake)


@router.post("/evaluate")
async def evaluate_site(
    address: str = Form(...),
    workload: str = Form("ai_hpc"),
    target_mw: float = Form(100),
    drive_folder_url: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
    stub: bool = Form(default=False),
    user=Depends(get_current_user),
):
    """Run a full site evaluation pipeline."""
    data = {
        "address": address,
        "workload": workload,
        "target_mw": str(target_mw),
        "stub": str(stub).lower(),
    }
    if drive_folder_url:
        data["drive_folder_url"] = drive_folder_url

    async with httpx.AsyncClient(timeout=300) as client:
        files_list = []
        for f in files:
            content = await f.read()
            files_list.append(("files", (f.filename, content, f.content_type)))

        resp = await client.post(
            f"{DATASITE_URL}/evaluate",
            data=data,
            files=files_list if files_list else None,
        )
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
        return resp.json()


# ---------------------------------------------------------------------------
# Site → Project advance (Sprint 2) — execute-on-approve
# ---------------------------------------------------------------------------

async def _find_project_for_site(db: AsyncSession, site_id: str) -> Project | None:
    res = await db.execute(select(Project).where(Project.site_id == site_id))
    return res.scalars().first()


async def _find_pending_advance(db: AsyncSession, site_id: str) -> ApprovalItem | None:
    res = await db.execute(
        select(ApprovalItem).where(
            ApprovalItem.workflow == SITE_ADVANCE_WORKFLOW,
            ApprovalItem.status == ApprovalStatus.PENDING.value,
        )
    )
    for item in res.scalars().all():
        if (item.payload or {}).get("site_id") == site_id:
            return item
    return None


@router.post("/{site_id}/advance", status_code=status.HTTP_202_ACCEPTED)
async def advance_site_to_project(
    site_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Request advancing an evaluated site to a Quill project.

    Lane-2 gated (execute-on-approve): this creates a pending approval in
    the queue. The Project row is only created when a human approves the
    item — see `execute_approval` in app/services/approvals.py.
    """
    existing = await _find_project_for_site(db, site_id)
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"site already advanced to project {existing.id}",
        )

    pending = await _find_pending_advance(db, site_id)
    if pending is not None:
        # Idempotent: don't create a duplicate approval for the same site.
        return {
            "site_id": site_id,
            "status": "pending_approval",
            "approval_id": pending.id,
            "detail": "an advance approval for this site is already pending",
        }

    site = await _datasite_request("get", f"/sites/{site_id}")

    prop = site.get("property") or {}
    rec = site.get("recommendation") or {}
    scores = site.get("scores") or {}
    address_parts = [prop.get("address"), prop.get("city"), prop.get("state"), prop.get("zip")]
    address = ", ".join(str(p) for p in address_parts if p) or "Unknown Site"
    verdict = rec.get("verdict")
    score = scores.get("total_weighted")
    workload = site.get("target_workload")

    notes_bits = []
    if rec.get("summary"):
        notes_bits.append(str(rec["summary"])[:800])
    if rec.get("next_steps"):
        notes_bits.append("Next steps: " + "; ".join(str(s) for s in rec["next_steps"][:5]))
    project_fields = {
        "name": f"{address.split(',')[0]} — {workload or 'Data Center'}",
        "address": address,
        "site_id": site_id,
        "site_score": score,
        "site_verdict": verdict,
        "workload_type": workload,
        "phase": "site_control",
        "status": "active",
        "notes": "\n\n".join(notes_bits) or None,
    }

    item = await approvals_svc.create_approval(
        db,
        payload={
            "agent_id": "site-pipeline",
            "agent_version": "1.0.0",
            "workflow": SITE_ADVANCE_WORKFLOW,
            "lane": Lane.SINGLE.value,
            "priority": "normal",
            "target_system": "none",
            "payload": {
                "kind": "create_project",
                "site_id": site_id,
                "requested_by": str(user.id),
                "project": project_fields,
            },
            "agent_confidence": 1.0,
            "agent_reasoning": (
                f"User {user.email} requested advancing site '{address}' "
                f"(score={score}, verdict={verdict}) to a Quill project."
            ),
        },
        actor=str(user.id),
    )

    return {
        "site_id": site_id,
        "status": "pending_approval",
        "approval_id": item.id,
        "project": project_fields,
        "detail": "Advance requires Lane-2 approval; the project is created on approve.",
    }


@router.get("/{site_id}/advance")
async def get_site_advance_status(
    site_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Advance state for the site detail UI:
    none | pending_approval | advanced."""
    project = await _find_project_for_site(db, site_id)
    if project is not None:
        return {
            "site_id": site_id,
            "status": "advanced",
            "project_id": project.id,
            "project_name": project.name,
        }
    pending = await _find_pending_advance(db, site_id)
    if pending is not None:
        return {
            "site_id": site_id,
            "status": "pending_approval",
            "approval_id": pending.id,
        }
    return {"site_id": site_id, "status": "none"}
