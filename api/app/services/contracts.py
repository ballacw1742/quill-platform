"""Contracts service — Sprint Contracts.1.

Coordinates the lifecycle of a contract upload/extraction run:

    POST /v1/contracts/upload
        ↓
    Contract row (status=uploaded) created; files written to blob store;
    text extraction kicked off in background → status=extracting → extracted
        ↓
    Contract-extractor daemon polls status=extracted, runs agent, produces
    contract_extraction.publish approval item.
        ↓
    Human approves → on_extraction_approved stamps Contract row.

Storage
-------
Files live under ``contracts/<upload_id>/raw/<filename>`` using the same
blob-path conventions as Estimates.  The blob root env var is
``CONTRACTS_BLOB_PATH`` (default ``./_local_contracts``).

Text extraction
---------------
Reuses pypdf (PDF) and python-docx (DOCX) directly; the Estimates drawing
extractor is drawing-specific and not appropriate here.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Contract
from app.services import audit as audit_svc

log = logging.getLogger("quill.contracts")
_settings = get_settings()

# ---------------------------------------------------------------------------
# Limits — mirror estimates where reasonable
# ---------------------------------------------------------------------------
MAX_FILE_BYTES = 100 * 1024 * 1024   # 100 MB per file
MAX_TOTAL_BYTES = 300 * 1024 * 1024  # 300 MB per upload
MAX_FILE_COUNT = 10

VALID_STATUSES = {
    "uploaded",
    "extracting",
    "extracted",
    "reviewing",
    "reviewed",
    "drafting",
    "drafted",
    "failed",
}

VALID_CONTRACT_TYPES = {
    "owner_gc",
    "subcontract",
    "change_order",
    "purchase_order",
    "letter_of_intent",
    "nda",
    "msa",
    "equipment_lease",
    "insurance_certificate",
    "lien_waiver",
    "other",
    "unknown",
}

_safe_re = re.compile(r"[^A-Za-z0-9._-]+")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_name(s: str) -> str:
    s = (s or "").strip()
    s = _safe_re.sub("_", s)
    return s[:128] or "file"


def _blob_root() -> Path:
    import os

    raw = (
        getattr(_settings, "CONTRACTS_BLOB_PATH", None)
        or os.environ.get("CONTRACTS_BLOB_PATH", "./_local_contracts")
    )
    p = Path(raw).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _raw_key(upload_id: str, filename: str) -> str:
    return f"contracts/{upload_id}/raw/{_safe_name(filename)}"


def _extracted_key(upload_id: str, name: str) -> str:
    return f"contracts/{upload_id}/extracted/{_safe_name(name)}"


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
class ContractUploadValidationError(ValueError):
    """Raised when an upload payload is rejected before persistence."""


def _validate_upload(files: list[dict[str, Any]]) -> None:
    if not files:
        raise ContractUploadValidationError("no files provided")
    if len(files) > MAX_FILE_COUNT:
        raise ContractUploadValidationError(
            f"too many files: {len(files)} > {MAX_FILE_COUNT}"
        )
    total = 0
    for f in files:
        size = int(f.get("size_bytes") or 0)
        if size > MAX_FILE_BYTES:
            name = f.get("filename") or "?"
            raise ContractUploadValidationError(
                f"{name!r} exceeds per-file cap ({size} > {MAX_FILE_BYTES})"
            )
        total += size
    if total > MAX_TOTAL_BYTES:
        raise ContractUploadValidationError(
            f"total upload size exceeds cap ({total} > {MAX_TOTAL_BYTES})"
        )


def _detect_kind(filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        return "pdf"
    if ext in ("docx", "doc"):
        return "docx"
    if ext == "txt":
        return "txt"
    return "other"


# ---------------------------------------------------------------------------
# Text extraction helpers (PDF + DOCX; no OCR)
# ---------------------------------------------------------------------------
def _extract_text_from_pdf(data: bytes) -> str:
    """Extract plain text from a PDF using pypdf."""
    try:
        import io

        import pypdf  # type: ignore[import]

        reader = pypdf.PdfReader(io.BytesIO(data))
        parts: list[str] = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                parts.append("")
        return "\n".join(parts)
    except ImportError:
        log.warning("contracts.pypdf_missing: install pypdf for PDF text extraction")
        return ""
    except Exception as exc:  # noqa: BLE001
        log.warning("contracts.pdf_extract_failed err=%s", exc)
        return ""


def _extract_text_from_docx(data: bytes) -> str:
    """Extract plain text from a DOCX using python-docx."""
    try:
        import io

        import docx  # type: ignore[import]

        doc = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs)
    except ImportError:
        log.warning("contracts.docx_missing: install python-docx for DOCX text extraction")
        return ""
    except Exception as exc:  # noqa: BLE001
        log.warning("contracts.docx_extract_failed err=%s", exc)
        return ""


def _extract_text(filename: str, data: bytes) -> str:
    """Dispatch text extraction by file kind."""
    kind = _detect_kind(filename)
    if kind == "pdf":
        return _extract_text_from_pdf(data)
    if kind == "docx":
        return _extract_text_from_docx(data)
    if kind == "txt":
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return ""
    # Fallback: try UTF-8 decode for unknown kinds
    try:
        return data.decode("utf-8", errors="replace")[:50_000]
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class ContractsService:
    """High-level contracts lifecycle. Stateless; takes a session per call."""

    # ---- Create / Upload --------------------------------------------------
    async def upload(
        self,
        session: AsyncSession,
        *,
        files: list[dict[str, Any]],
        project_label: str = "",
        contract_type: str | None = None,
        notes: str = "",
        actor: str = "system",
    ) -> Contract:
        """Create a Contract row, persist files to the blob layer, and
        kick off text extraction in the background.

        ``files[]`` is a list of dicts shaped like:
          { filename: str, size_bytes: int, content: bytes }

        Returns the persisted Contract (status='uploaded').
        """
        _validate_upload(files)

        if contract_type and contract_type not in VALID_CONTRACT_TYPES:
            raise ContractUploadValidationError(
                f"unknown contract_type {contract_type!r}; "
                f"valid: {sorted(VALID_CONTRACT_TYPES)}"
            )

        upload_id = str(uuid.uuid4())
        manifest: list[dict[str, Any]] = []

        for f in files:
            name = f.get("filename") or "upload.bin"
            content: bytes = f.get("content") or b""
            kind = _detect_kind(name)
            key = _raw_key(upload_id, name)
            try:
                _write_blob(key, content)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "contracts.blob_write_failed key=%s err=%s", key, exc
                )
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

        contract = Contract(
            upload_id=upload_id,
            project_label=(project_label or "")[:200],
            contract_type=contract_type,
            notes=(notes or "")[:10_000],
            status="uploaded",
            uploaded_files=manifest,
            parties=[],
        )
        session.add(contract)
        await session.flush()

        await audit_svc.record_event(
            session,
            event_type="contract.uploaded",
            actor=actor,
            approval_item_id=None,
            payload={
                "upload_id": upload_id,
                "contract_id": contract.id,
                "file_count": len(manifest),
                "project_label": contract.project_label,
            },
        )
        await session.commit()

        # Kick off text extraction in the background.
        try:
            asyncio.get_event_loop().create_task(
                self._run_extraction_async(upload_id)
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "contracts.extraction_schedule_failed upload_id=%s err=%s",
                upload_id, exc,
            )

        return contract

    # ---- Read -------------------------------------------------------------
    async def get_status(
        self, session: AsyncSession, upload_id: str
    ) -> Contract | None:
        res = await session.execute(
            select(Contract).where(Contract.upload_id == upload_id)
        )
        return res.scalar_one_or_none()

    async def list_contracts(
        self,
        session: AsyncSession,
        *,
        status: str | None = None,
        contract_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Contract], int]:
        """Return a paginated list of Contract rows ordered by created_at DESC."""
        if status is not None and status not in VALID_STATUSES:
            raise ValueError(f"invalid status filter {status!r}")
        if contract_type is not None and contract_type not in VALID_CONTRACT_TYPES:
            raise ValueError(f"invalid contract_type filter {contract_type!r}")

        limit = max(1, min(int(limit or 50), 200))
        offset = max(0, int(offset or 0))

        q = select(Contract)
        cq = select(func.count()).select_from(Contract)
        if status:
            q = q.where(Contract.status == status)
            cq = cq.where(Contract.status == status)
        if contract_type:
            q = q.where(Contract.contract_type == contract_type)
            cq = cq.where(Contract.contract_type == contract_type)
        q = q.order_by(Contract.created_at.desc()).limit(limit).offset(offset)

        res = await session.execute(q)
        items = list(res.scalars().all())
        total_res = await session.execute(cq)
        total = int(total_res.scalar_one() or 0)
        return items, total

    # ---- Lifecycle --------------------------------------------------------
    async def mark_status(
        self,
        session: AsyncSession,
        upload_id: str,
        *,
        status: str,
        error_message: str | None = None,
        actor: str = "system",
    ) -> Contract:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}")
        contract = await self.get_status(session, upload_id)
        if contract is None:
            raise LookupError(f"contract upload_id={upload_id} not found")
        prior = contract.status
        contract.status = status
        contract.updated_at = _utcnow()
        if error_message is not None:
            contract.error_message = error_message[:4000]
        await audit_svc.record_event(
            session,
            event_type=f"contract.status.{status}",
            actor=actor,
            approval_item_id=None,
            payload={
                "upload_id": upload_id,
                "from": prior,
                "to": status,
                "error_message": contract.error_message,
            },
        )
        await session.commit()
        return contract

    # ---- Approval hook ---------------------------------------------------
    async def on_extraction_approved(
        self,
        session: AsyncSession,
        *,
        upload_id: str | None,
        artifact_id: str,
        actor: str = "system",
    ) -> Contract | None:
        """Called by approvals.execute_approval when a contract_extraction
        artifact is approved + executed. Stamps the Contract row with the
        artifact pointer and denormalized fields from extracted_fields.
        """
        if upload_id is None:
            return None
        contract = await self.get_status(session, upload_id)
        if contract is None:
            log.warning(
                "contracts.extraction_no_contract upload_id=%s", upload_id
            )
            return None
        contract.classification_artifact_id = artifact_id
        contract.status = "extracted"
        contract.updated_at = _utcnow()
        await audit_svc.record_event(
            session,
            event_type="contract.extraction_approved",
            actor=actor,
            approval_item_id=None,
            payload={
                "upload_id": upload_id,
                "contract_id": contract.id,
                "classification_artifact_id": artifact_id,
            },
        )
        await session.commit()
        return contract

    # ---- Background text extraction --------------------------------------
    async def _run_extraction_async(self, upload_id: str) -> None:
        """Best-effort background text extraction.

        Reads raw files from blob, extracts plain text from PDFs/DOCX/TXT,
        writes per-file extraction summaries back into the manifest, and
        flips status from ``uploaded`` → ``extracting`` → ``extracted``.

        The actual structured-field extraction (contract-extractor agent run)
        is dispatched by the contract_dispatcher daemon which polls for
        status=``extracted``.
        """
        from app.db import SessionLocal  # avoid circular at import time

        try:
            async with SessionLocal() as s:
                contract = await self.get_status(s, upload_id)
                if contract is None:
                    return
                contract.status = "extracting"
                contract.updated_at = _utcnow()
                await s.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "contracts.extraction_status_set_failed err=%s", exc
            )
            return

        new_manifest: list[dict[str, Any]] = []
        any_ok = False
        any_failed = False

        async with SessionLocal() as s:
            contract = await self.get_status(s, upload_id)
            if contract is None:
                return

            for entry in (contract.uploaded_files or []):
                key = entry.get("minio_key")
                fname = entry.get("filename") or "file"
                try:
                    data = _read_blob(key) if key else b""
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "contracts.extraction_read_failed key=%s err=%s",
                        key, exc,
                    )
                    new_manifest.append(
                        {
                            **entry,
                            "extraction_status": "failed",
                            "extraction_summary": f"blob read failed: {exc}",
                        }
                    )
                    any_failed = True
                    continue

                try:
                    text = _extract_text(fname, data)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "contracts.text_extract_threw upload_id=%s file=%s err=%s",
                        upload_id, fname, exc,
                    )
                    new_manifest.append(
                        {
                            **entry,
                            "extraction_status": "failed",
                            "extraction_summary": f"extraction threw: {exc}",
                        }
                    )
                    any_failed = True
                    continue

                # Write extracted text blob
                ext_summary = text[:4000] if text else "(empty)"
                try:
                    ext_key = _extracted_key(upload_id, f"{_safe_name(fname)}.txt")
                    _write_blob(ext_key, text.encode("utf-8"))
                    ext_minio_key = ext_key
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "contracts.extracted_write_failed err=%s", exc
                    )
                    ext_minio_key = None

                status_val = "ok" if text.strip() else "partial"
                if text.strip():
                    any_ok = True
                else:
                    any_failed = True

                new_manifest.append(
                    {
                        **entry,
                        "extraction_status": status_val,
                        "extraction_summary": ext_summary,
                        "extracted_text_key": ext_minio_key,
                    }
                )

            contract.uploaded_files = new_manifest

            # Flip to extracted if at least one file was readable.
            if any_ok:
                contract.status = "extracted"
            elif any_failed:
                contract.status = "failed"
                contract.error_message = "all files failed text extraction"
            else:
                contract.status = "extracted"  # empty but not failed

            contract.updated_at = _utcnow()

            try:
                await audit_svc.record_event(
                    s,
                    event_type="contract.extract_complete",
                    actor="system",
                    approval_item_id=None,
                    payload={
                        "upload_id": upload_id,
                        "contract_id": contract.id,
                        "any_ok": any_ok,
                        "any_failed": any_failed,
                        "files": [
                            {
                                "filename": f["filename"],
                                "kind": f["kind"],
                                "status": f["extraction_status"],
                            }
                            for f in new_manifest
                        ],
                    },
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("contracts.audit_event_failed err=%s", exc)

            await s.commit()


# Module-level singleton.
service = ContractsService()


__all__ = [
    "ContractsService",
    "service",
    "ContractUploadValidationError",
    "VALID_STATUSES",
    "VALID_CONTRACT_TYPES",
    "MAX_FILE_BYTES",
    "MAX_TOTAL_BYTES",
    "MAX_FILE_COUNT",
]
