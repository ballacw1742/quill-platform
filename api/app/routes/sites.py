"""
Quill Sites routes — proxies to DataSite Intelligence Cloud Run service.
Surfaces site evaluation functionality within the Quill platform.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

import httpx

from app.db import get_db
from app.security import get_current_user

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


@router.post("/{site_id}/advance")
async def advance_site_to_project(
    site_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Advance an evaluated site to a Quill project.
    Creates a new project pre-populated with site data.
    This is the DataSite → Quill bridge endpoint.
    """
    site = await _datasite_request("get", f"/sites/{site_id}")

    address = site.get("property", {}).get("address", "Unknown Site")
    state = site.get("property", {}).get("state", "")
    verdict = site.get("recommendation", {}).get("verdict", "")
    score = site.get("scores", {}).get("total_weighted", 0)

    return {
        "site_id": site_id,
        "address": address,
        "state": state,
        "verdict": verdict,
        "score": score,
        "message": "Site advanced. Project creation coming in Sprint 2.",
        "site_data": {
            "address": address,
            "workload": site.get("target_workload"),
            "target_mw": site.get("target_mw"),
            "power_notes": site.get("research", {}).get("power", {}).get("notes", "")[:500],
            "fiber_notes": site.get("research", {}).get("fiber", {}).get("notes", "")[:300],
            "risks": site.get("recommendation", {}).get("risks", []),
            "strengths": site.get("recommendation", {}).get("strengths", []),
            "next_steps": site.get("recommendation", {}).get("next_steps", []),
        },
    }
