"""Estimates service — Phase G.1.

Coordinates the lifecycle of an estimate run:

    POST /v1/estimates/upload
        ↓
    Estimate row (status=queued) created; files written to MinIO/local;
    extraction kicked off in background → status=extracting → done
        ↓
    POST /v1/estimates/{upload_id}/start_estimation
        ↓
    Dispatches the design-classifier agent (status=classifying);
    on classification approval, dispatches the estimator-scheduler
    (status=estimating); on package approval, status=done with
    package_artifact_id set.

Storage
-------
v0.1 mirrors the Documents-service pattern: blob root is a local
filesystem path (`settings.ESTIMATES_BLOB_PATH`, default
`./_local_estimates`). A real MinIO/S3 backend will plug in here without
changing call-sites; the path key (`estimates/<upload_id>/raw/<filename>`)
is already S3-friendly.

Agent dispatch
--------------
We do not import the prompts repo at runtime. Instead the runtime
subprocess pattern (see `runtime/`) is used: this service writes a
"work order" (input JSON) to a path and emits an audit event the
runtime picks up. v0.1 implements the wire-up; the actual agent
subprocess is a thin shim that the runtime layer attaches to. Tests
exercise the wire-up by mocking the dispatcher.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Estimate
from app.services import audit as audit_svc
from app.services.drawings import DrawingExtractionResult, detect_kind, extract

log = logging.getLogger("quill.estimates")
_settings = get_settings()


VALID_STATUSES = {
    "queued",
    "extracting",
    "classifying",
    "estimating",
    "done",
    "failed",
}

ALLOWED_KINDS = {"pdf", "ifc", "dxf", "dwg", "rvt"}
"""Phase G.4 expands the accepted set; DWG flows through ODA File Converter
if present (else returns a friendly needs_conversion status); RVT flows
through Autodesk APS if creds are present (else not_configured)."""

MAX_FILE_BYTES = 200 * 1024 * 1024  # 200 MB per file
MAX_TOTAL_BYTES = 600 * 1024 * 1024  # 600 MB per upload
MAX_FILE_COUNT = 20

_safe_re = re.compile(r"[^A-Za-z0-9._-]+")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_name(s: str) -> str:
    s = (s or "").strip()
    s = _safe_re.sub("_", s)
    return s[:128] or "file"


def _blob_root() -> Path:
    raw = (
        getattr(_settings, "ESTIMATES_BLOB_PATH", None)
        or os.environ.get("ESTIMATES_BLOB_PATH", "./_local_estimates")
    )
    p = Path(raw).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _raw_key(upload_id: str, filename: str) -> str:
    return f"estimates/{upload_id}/raw/{_safe_name(filename)}"


def _extracted_key(upload_id: str, name: str) -> str:
    return f"estimates/{upload_id}/extracted/{_safe_name(name)}"


def _write_blob(rel_key: str, body: bytes) -> Path:
    root = _blob_root()
    target = (root / rel_key).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError(f"blob path escapes root: {rel_key}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return target


def _read_blob(rel_key: str) -> bytes:
    root = _blob_root()
    target = (root / rel_key).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError(f"blob path escapes root: {rel_key}")
    return target.read_bytes()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
class UploadValidationError(ValueError):
    """Raised when an upload payload is rejected before persistence."""


def _validate_upload(files: list[dict[str, Any]]) -> None:
    if not files:
        raise UploadValidationError("no files provided")
    if len(files) > MAX_FILE_COUNT:
        raise UploadValidationError(
            f"too many files: {len(files)} > {MAX_FILE_COUNT}"
        )
    total = 0
    for f in files:
        name = f.get("filename") or ""
        kind = detect_kind(name)
        if kind not in ALLOWED_KINDS:
            raise UploadValidationError(
                f"unsupported file kind for {name!r}: only "
                f"{sorted(ALLOWED_KINDS)} allowed in v0.1"
            )
        size = int(f.get("size_bytes") or 0)
        if size > MAX_FILE_BYTES:
            raise UploadValidationError(
                f"{name!r} exceeds per-file cap ({size} > {MAX_FILE_BYTES})"
            )
        total += size
    if total > MAX_TOTAL_BYTES:
        raise UploadValidationError(
            f"total upload size exceeds cap ({total} > {MAX_TOTAL_BYTES})"
        )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class EstimatesService:
    """High-level estimates lifecycle. Stateless; takes a session per call."""

    # ---- Create / Upload --------------------------------------------------
    async def upload(
        self,
        session: AsyncSession,
        *,
        files: list[dict[str, Any]],
        project_label: str = "",
        notes: str = "",
        actor: str = "system",
    ) -> Estimate:
        """Create an Estimate row, persist files to the blob layer, and
        kick off extraction in the background.

        `files[]` is a list of dicts shaped like:
          { filename: str, size_bytes: int, content: bytes, kind: optional str }

        Returns the persisted Estimate (status='queued').
        """
        _validate_upload(files)

        upload_id = str(uuid.uuid4())
        manifest: list[dict[str, Any]] = []

        for f in files:
            name = f.get("filename") or "upload.bin"
            content: bytes = f.get("content") or b""
            kind = detect_kind(name)
            key = _raw_key(upload_id, name)
            try:
                _write_blob(key, content)
            except Exception as exc:  # noqa: BLE001
                log.warning("estimates.blob_write_failed key=%s err=%s", key, exc)
            manifest.append(
                {
                    "filename": _safe_name(name),
                    "kind": kind,
                    "size_bytes": int(f.get("size_bytes") or len(content)),
                    "extraction_status": "pending",
                    "extraction_summary": "",
                    "minio_key": key,
                }
            )

        est = Estimate(
            upload_id=upload_id,
            project_label=(project_label or "")[:200],
            notes=(notes or "")[:2000],
            status="queued",
            uploaded_files=manifest,
        )
        session.add(est)
        await session.flush()

        await audit_svc.record_event(
            session,
            event_type="estimate.uploaded",
            actor=actor,
            approval_item_id=None,
            payload={
                "upload_id": upload_id,
                "estimate_id": est.id,
                "file_count": len(manifest),
                "kinds": sorted({m["kind"] for m in manifest}),
                "project_label": est.project_label,
            },
        )
        await session.commit()

        # Schedule extraction in the background. We keep the file bytes in
        # memory only briefly; the kicked-off task re-reads from blob.
        try:
            asyncio.get_event_loop().create_task(
                self._run_extraction_async(upload_id)
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "estimates.extraction_schedule_failed upload_id=%s err=%s",
                upload_id, exc,
            )

        return est

    # ---- Read -------------------------------------------------------------
    async def get_status(
        self, session: AsyncSession, upload_id: str
    ) -> Estimate | None:
        res = await session.execute(
            select(Estimate).where(Estimate.upload_id == upload_id)
        )
        return res.scalar_one_or_none()

    async def list_estimates(
        self,
        session: AsyncSession,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Estimate], int]:
        """Return a paginated list of Estimate rows ordered by created_at
        DESC, plus the total matching count.

        The Estimate model isn't user-scoped in v0.1 (single-tenant), so this
        is effectively a global listing. Auth is enforced at the route layer
        (`get_current_user_or_agent`).
        """
        from sqlalchemy import func

        if status is not None and status not in VALID_STATUSES:
            raise ValueError(f"invalid status filter {status!r}")
        limit = max(1, min(int(limit or 50), 200))
        offset = max(0, int(offset or 0))

        q = select(Estimate)
        cq = select(func.count()).select_from(Estimate)
        if status:
            q = q.where(Estimate.status == status)
            cq = cq.where(Estimate.status == status)
        q = q.order_by(Estimate.created_at.desc()).limit(limit).offset(offset)

        res = await session.execute(q)
        items = list(res.scalars().all())
        total_res = await session.execute(cq)
        total = int(total_res.scalar_one() or 0)
        return items, total

    # ---- Lifecycle hooks --------------------------------------------------
    async def mark_status(
        self,
        session: AsyncSession,
        upload_id: str,
        *,
        status: str,
        error_message: str | None = None,
        actor: str = "system",
    ) -> Estimate:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}")
        est = await self.get_status(session, upload_id)
        if est is None:
            raise LookupError(f"estimate upload_id={upload_id} not found")
        prior = est.status
        est.status = status
        est.updated_at = _utcnow()
        if error_message is not None:
            est.error_message = error_message[:4000]
        await audit_svc.record_event(
            session,
            event_type=f"estimate.status.{status}",
            actor=actor,
            approval_item_id=None,
            payload={
                "upload_id": upload_id,
                "from": prior,
                "to": status,
                "error_message": est.error_message,
            },
        )
        await session.commit()
        return est

    # ---- Start estimation -------------------------------------------------
    async def start_estimation(
        self,
        session: AsyncSession,
        upload_id: str,
        *,
        actor: str = "system",
    ) -> dict[str, Any]:
        """Called after the AACE classification has been approved. Dispatches
        the estimator-scheduler agent run.

        v0.1 wire-up: we record an audit event + flip status to 'estimating'.
        The actual agent run is dispatched by the runtime subprocess
        layer, which polls audit events of type 'estimate.dispatch'.
        """
        est = await self.get_status(session, upload_id)
        if est is None:
            raise LookupError(f"estimate upload_id={upload_id} not found")
        if est.classification_artifact_id is None:
            raise ValueError(
                f"cannot start estimation: classification not yet "
                f"approved (upload_id={upload_id})"
            )

        await self.mark_status(
            session, upload_id, status="estimating", actor=actor
        )
        entry = await audit_svc.record_event(
            session,
            event_type="estimate.dispatch",
            actor=actor,
            approval_item_id=None,
            payload={
                "upload_id": upload_id,
                "estimate_id": est.id,
                "classification_artifact_id": est.classification_artifact_id,
                "agent_id": "estimator-scheduler",
            },
        )
        await session.commit()
        return {
            "ok": True,
            "upload_id": upload_id,
            "audit_hash": entry.hash,
            "agent_id": "estimator-scheduler",
        }

    # ---- Approval-execute hooks ------------------------------------------
    async def on_classification_approved(
        self,
        session: AsyncSession,
        *,
        upload_id: str | None,
        artifact_id: str,
        actor: str = "system",
    ) -> Estimate | None:
        """Called by approvals.execute_approval when an aace_classification
        artifact is approved + executed. Stamps the Estimate row.
        """
        if upload_id is None:
            return None
        est = await self.get_status(session, upload_id)
        if est is None:
            log.warning(
                "estimates.classification_no_estimate upload_id=%s",
                upload_id,
            )
            return None
        est.classification_artifact_id = artifact_id
        est.status = "classifying"  # transient; user must POST start_estimation
        est.updated_at = _utcnow()
        await audit_svc.record_event(
            session,
            event_type="estimate.classification_approved",
            actor=actor,
            approval_item_id=None,
            payload={
                "upload_id": upload_id,
                "estimate_id": est.id,
                "classification_artifact_id": artifact_id,
            },
        )
        await session.commit()
        return est

    async def on_package_approved(
        self,
        session: AsyncSession,
        *,
        upload_id: str | None,
        artifact_id: str,
        actor: str = "system",
    ) -> Estimate | None:
        """Called by approvals.execute_approval when a cost_schedule_package
        artifact is approved + executed. Stamps the Estimate row to done.
        """
        if upload_id is None:
            return None
        est = await self.get_status(session, upload_id)
        if est is None:
            log.warning(
                "estimates.package_no_estimate upload_id=%s", upload_id
            )
            return None
        est.package_artifact_id = artifact_id
        est.status = "done"
        est.updated_at = _utcnow()
        await audit_svc.record_event(
            session,
            event_type="estimate.package_approved",
            actor=actor,
            approval_item_id=None,
            payload={
                "upload_id": upload_id,
                "estimate_id": est.id,
                "package_artifact_id": artifact_id,
            },
        )
        await session.commit()
        return est

    # ---- Extraction (background) ----------------------------------------
    async def _run_extraction_async(self, upload_id: str) -> None:
        """Best-effort background extraction. Reads files from blob, runs
        each through the drawings extractor, and writes per-file
        extraction summaries back to the Estimate.uploaded_files manifest.
        """
        from app.db import SessionLocal  # avoid circular at import time

        try:
            async with SessionLocal() as s:
                est = await self.get_status(s, upload_id)
                if est is None:
                    return
                est.status = "extracting"
                est.updated_at = _utcnow()
                await s.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("estimates.extraction_status_set_failed err=%s", exc)
            return

        new_manifest: list[dict[str, Any]] = []
        any_failed = False
        async with SessionLocal() as s:
            est = await self.get_status(s, upload_id)
            if est is None:
                return
            for entry in (est.uploaded_files or []):
                key = entry.get("minio_key")
                fname = entry.get("filename")
                try:
                    data = _read_blob(key) if key else b""
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "estimates.extraction_read_failed key=%s err=%s",
                        key, exc,
                    )
                    new_manifest.append(
                        {**entry, "extraction_status": "failed",
                         "extraction_summary": f"blob read failed: {exc}"}
                    )
                    any_failed = True
                    continue

                try:
                    result = extract(filename=fname, data=data)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "estimates.extract_threw upload_id=%s file=%s err=%s",
                        upload_id, fname, exc,
                    )
                    new_manifest.append(
                        {**entry, "extraction_status": "failed",
                         "extraction_summary": f"extract threw: {exc}"}
                    )
                    any_failed = True
                    continue

                if result.extraction_status == "failed":
                    any_failed = True

                # Write the rich extraction artifact (entities, quantities,
                # renders) to the extracted/ side of the upload.
                try:
                    art = {
                        "filename": result.filename,
                        "kind": result.kind,
                        "extraction_status": result.extraction_status,
                        "summary": result.summary,
                        "entities": result.entities,
                        "quantities": result.quantities,
                        "renders": result.renders,
                        "errors": result.errors,
                    }
                    art_key = _extracted_key(
                        upload_id, f"{result.filename}.json"
                    )
                    _write_blob(art_key, json.dumps(art).encode("utf-8"))
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "estimates.extracted_write_failed err=%s", exc
                    )

                new_manifest.append({
                    **entry,
                    "extraction_status": result.extraction_status,
                    "extraction_summary": result.summary[:4000],
                })

            est.uploaded_files = new_manifest
            est.status = "failed" if (any_failed and all(
                f.get("extraction_status") == "failed" for f in new_manifest
            )) else "queued"
            # If we still have at least one OK/partial extraction we leave
            # it queued (waiting for /start_estimation) since the
            # classification step is gated on user / agent action.
            est.updated_at = _utcnow()
            try:
                await audit_svc.record_event(
                    s,
                    event_type="estimate.extraction_complete",
                    actor="system",
                    approval_item_id=None,
                    payload={
                        "upload_id": upload_id,
                        "estimate_id": est.id,
                        "any_failed": any_failed,
                        "files": [
                            {"filename": f["filename"],
                             "kind": f["kind"],
                             "status": f["extraction_status"]}
                            for f in new_manifest
                        ],
                    },
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "estimates.audit_event_failed err=%s", exc
                )
            await s.commit()


# Module-level singleton for convenience.
service = EstimatesService()


__all__ = [
    "EstimatesService",
    "service",
    "ALLOWED_KINDS",
    "MAX_FILE_BYTES",
    "MAX_TOTAL_BYTES",
    "MAX_FILE_COUNT",
    "UploadValidationError",
]
