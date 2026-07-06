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
from app.models import Contract, ContractInterpretation, Document
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
        source: str | None = None,
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
        if source:
            q = q.where(Contract.source == source)
            cq = cq.where(Contract.source == source)
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
        fields: dict[str, Any] | None = None,
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
        # Sprint 4 fix: this docstring always promised denormalized stamping,
        # but nothing ever wrote extracted_fields — which permanently blocked
        # the reviewer daemon (it skips contracts with extracted_fields=None).
        if fields:
            contract.extracted_fields = fields
            ct = fields.get("contract_type")
            if isinstance(ct, str) and ct:
                contract.contract_type = ct
            parties = fields.get("parties")
            if isinstance(parties, (list, dict)) and parties:
                contract.parties = parties
            for col in ("effective_date", "expiration_date"):
                v = fields.get(col)
                if isinstance(v, str) and v:
                    try:
                        setattr(contract, col, datetime.fromisoformat(v))
                    except ValueError:
                        pass  # non-ISO date string — leave column unset
            tv = fields.get("total_value_usd")
            if isinstance(tv, (int, float)):
                contract.total_value_usd = tv
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

    # ---- Blob access (Sprint 4 — remote daemons) -------------------------
    def read_extracted_text(self, upload_id: str, filename: str) -> str | None:
        """Return the extracted plain text for one uploaded file, or None.

        Sprint 4: the contract dispatcher daemons may run on a different host
        than the API. This gives them an HTTP path to the full extracted text
        (the manifest's ``extraction_summary`` is capped at 4000 chars).
        """
        key = _extracted_key(upload_id, f"{_safe_name(filename)}.txt")
        try:
            return _read_blob(key).decode("utf-8")
        except FileNotFoundError:
            return None
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            log.warning(
                "contracts.extracted_read_failed upload_id=%s file=%s err=%s",
                upload_id, filename, exc,
            )
            return None

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


    # ---- Contracts.2: Review hook -----------------------------------------
    async def on_review_approved(
        self,
        session: AsyncSession,
        *,
        upload_id: str | None,
        artifact_id: str,
        actor: str = "system",
    ) -> Contract | None:
        """Called by approvals.execute_approval when a contract_review artifact
        is approved + executed. Stamps Contract.review_artifact_id and flips
        status to 'reviewed'.
        """
        if upload_id is None:
            return None
        contract = await self.get_status(session, upload_id)
        if contract is None:
            log.warning("contracts.review_no_contract upload_id=%s", upload_id)
            return None
        contract.review_artifact_id = artifact_id
        contract.status = "reviewed"
        contract.updated_at = _utcnow()
        await audit_svc.record_event(
            session,
            event_type="contract.review_approved",
            actor=actor,
            approval_item_id=None,
            payload={
                "upload_id": upload_id,
                "contract_id": contract.id,
                "review_artifact_id": artifact_id,
            },
        )
        await session.commit()
        return contract

    # ---- Contracts.2: Interpret clause -------------------------------------
    async def interpret_clause(
        self,
        session: AsyncSession,
        *,
        upload_id: str,
        question: str,
        user: Any,
    ) -> dict[str, Any]:
        """Synchronous agent call: answer a plain-English question about this
        contract. Persists the Q&A row, audits, and returns the response dict.
        """
        from pathlib import Path as _Path
        import json as _json

        contract = await self.get_status(session, upload_id)
        if contract is None:
            raise LookupError(f"contract {upload_id!r} not found")
        if contract.extracted_fields is None:
            raise ValueError("extraction not yet complete for this contract")

        # Build raw text from blob (best-effort)
        blob_root = _blob_root()
        raw_text_parts: list[str] = []
        for entry in (contract.uploaded_files or []):
            ext_key = entry.get("extracted_text_key")
            if ext_key:
                key_path = (blob_root / ext_key).resolve()
                if str(key_path).startswith(str(blob_root)) and key_path.exists():
                    try:
                        raw_text_parts.append(key_path.read_text("utf-8"))
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "contracts.interpret_read_text_blob err=%s", exc
                        )
        raw_text = "\n\n".join(raw_text_parts) or (
            contract.extracted_fields.get("plain_english_summary", "")
        )

        agent_input: dict[str, Any] = {
            "contract_extraction": contract.extracted_fields,
            "raw_text_excerpt": raw_text[:20000],  # cap to avoid token overrun
            "question": question,
        }

        # Run the interpreter agent synchronously.
        try:
            from runtime.agent import Agent  # type: ignore
            from runtime.config import get_config  # type: ignore

            cfg = get_config()
            agent = Agent("contract-interpreter", config=cfg)
            run = await agent.run(agent_input, submit_to_queue=False, prompt_cache=False)
        except Exception as exc:  # noqa: BLE001
            log.error("contracts.interpret_agent_failed upload_id=%s err=%s", upload_id, exc)
            raise RuntimeError(f"agent invocation failed: {exc}") from exc

        if run.output is None:
            raise RuntimeError(f"interpreter agent returned no output (error={run.error!r})")

        output: dict[str, Any] = run.output
        # Ensure disclaimer is present.
        output.setdefault(
            "disclaimer",
            "AI-generated analysis. This is not legal advice. "
            "Review with qualified counsel before relying on it for any binding decision.",
        )

        # Persist the interpretation row.
        row_id = str(uuid.uuid4())
        interp_row = ContractInterpretation(
            id=row_id,
            contract_upload_id=upload_id,
            question=question,
            answer_json=output,
            asked_by=getattr(user, "id", str(user)),
        )
        session.add(interp_row)

        await audit_svc.record_event(
            session,
            event_type="contract.interpreted",
            actor=getattr(user, "id", "system"),
            approval_item_id=None,
            payload={
                "upload_id": upload_id,
                "interpretation_id": row_id,
                "question_len": len(question),
            },
        )
        await session.commit()

        return {
            **output,
            "contract_upload_id": upload_id,
            "interpretation_id": row_id,
            "created_at": interp_row.created_at,
        }

    # ---- Contracts.2: List reviews -----------------------------------------
    async def list_reviews(
        self,
        session: AsyncSession,
        *,
        upload_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return past contract_review.publish artifacts for this contract.

        Each review is stored as a Document once approved; we look up
        Documents by artifact_type + contract_upload_id in their metadata.
        Returns a lightweight list of {review_artifact_id, created_at,
        severity_counts} dicts.
        """
        from sqlalchemy import text as _text

        # Look for published Document rows whose extra_metadata contains
        # a 'contract_upload_id' matching our upload_id and artifact_type
        # of 'contract_review'.
        stmt = (
            select(Document)
            .where(
                Document.agent_id == "contract-reviewer",
            )
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        docs = result.scalars().all()

        # Filter in Python to avoid JSON query portability issues.
        out: list[dict[str, Any]] = []
        for doc in docs:
            meta = doc.meta or {}
            if meta.get("contract_upload_id") != upload_id:
                continue
            artifact = meta.get("artifact") or {}
            risk_flags = artifact.get("risk_flags") or []
            counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
            for flag in risk_flags:
                sev = flag.get("severity", "info")
                if sev in counts:
                    counts[sev] += 1
            out.append({
                "review_artifact_id": doc.id,
                "created_at": doc.created_at,
                "severity_counts": counts,
            })
        return out

    # ---- Contracts.2: List interpretations --------------------------------
    async def list_interpretations(
        self,
        session: AsyncSession,
        *,
        upload_id: str,
        limit: int = 50,
    ) -> tuple[list[ContractInterpretation], int]:
        """Return Q&A history for a contract (newest first)."""
        stmt = (
            select(ContractInterpretation)
            .where(ContractInterpretation.contract_upload_id == upload_id)
            .order_by(ContractInterpretation.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

        count_stmt = select(func.count()).where(
            ContractInterpretation.contract_upload_id == upload_id
        )
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one()

        return rows, total


    # ---- Contracts.3: Draft request -----------------------------------------
    async def create_draft_request(
        self,
        session: AsyncSession,
        *,
        request: Any,  # ContractDraftRequest (avoid circular at import time)
        user: Any,
    ) -> Contract:
        """Create a new Contract row for a drafting workflow.

        Does NOT kick off an async extraction — the contract-draft-dispatcher
        polls for status='drafting' and dispatches the agent.
        """
        import json as _json

        upload_id = str(uuid.uuid4())
        req_dict = request.dict() if hasattr(request, "dict") else dict(request)

        contract = Contract(
            upload_id=upload_id,
            project_label=(req_dict.get("scope_summary") or "")[:200],
            contract_type=req_dict.get("contract_type"),
            status="drafting",
            source="drafted",
            mode=req_dict.get("mode"),
            draft_request=req_dict,
            parties=list(req_dict.get("parties") or []),
            notes=req_dict.get("notes") or "",
            uploaded_files=[],
        )
        session.add(contract)
        await session.flush()

        # Write a priority-marker file for the dispatcher to find
        try:
            state_root = Path(__file__).resolve().parents[3] / "_state" / "contract_draft_requests"
            state_root.mkdir(parents=True, exist_ok=True)
            marker = {
                "upload_id": upload_id,
                "mode": req_dict.get("mode"),
                "contract_type": req_dict.get("contract_type"),
                "created_at": _utcnow().isoformat(),
            }
            (state_root / f"{upload_id}.json").write_text(
                _json.dumps(marker, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "contracts.draft_marker_write_failed upload_id=%s err=%s",
                upload_id, exc,
            )

        await audit_svc.record_event(
            session,
            event_type="contract.draft_request_created",
            actor=getattr(user, "id", "system"),
            approval_item_id=None,
            payload={
                "upload_id": upload_id,
                "mode": req_dict.get("mode"),
                "contract_type": req_dict.get("contract_type"),
            },
        )
        await session.commit()
        return contract

    # ---- Contracts.3: Redraft -------------------------------------------------
    async def request_redraft(
        self,
        session: AsyncSession,
        *,
        parent_upload_id: str,
        revision_notes: str,
        key_terms_overrides: list[dict] | None,
        user: Any,
    ) -> Contract:
        """Clone a draft request with revisions and create a new Contract row."""
        from app.schemas import ContractDraftRequest as _Schema

        parent = await self.get_status(session, parent_upload_id)
        if parent is None:
            raise LookupError(f"contract upload_id={parent_upload_id!r} not found")
        if parent.source != "drafted" or parent.draft_request is None:
            raise ValueError("parent contract is not a drafted contract or has no draft_request")

        new_req = dict(parent.draft_request)
        # Append revision_notes to notes
        existing_notes = new_req.get("notes") or ""
        new_req["notes"] = (existing_notes + "\n\nRevision: " + revision_notes).strip()
        # Merge key_terms_overrides
        if key_terms_overrides:
            existing_terms = list(new_req.get("key_terms_requested") or [])
            override_topics = {o.get("topic") for o in key_terms_overrides if o.get("topic")}
            existing_terms = [t for t in existing_terms if t.get("topic") not in override_topics]
            existing_terms.extend(key_terms_overrides)
            new_req["key_terms_requested"] = existing_terms
        # Mark the parent in the request
        new_req["prior_contract_upload_id"] = parent_upload_id

        # Build a schema instance for reuse
        try:
            draft_req = _Schema(**new_req)
        except Exception:  # noqa: BLE001
            # If schema parse fails, use a passthrough approach
            class _FallbackReq:
                def dict(self):
                    return new_req
                def __getattr__(self, name):
                    return new_req.get(name)
            draft_req = _FallbackReq()  # type: ignore[assignment]

        return await self.create_draft_request(session, request=draft_req, user=user)

    # ---- Contracts.3: Draft approved hook ------------------------------------
    async def on_draft_approved(
        self,
        session: AsyncSession,
        *,
        upload_id: str | None,
        artifact_id: str,
        actor: str = "system",
    ) -> Contract | None:
        """Called when a contract_draft.publish approval is executed.

        - Loads the Document artifact
        - Writes body_markdown to blob
        - Appends blob entry to uploaded_files
        - Stamps draft_artifact_id
        - Flips status to 'drafted'
        """
        if upload_id is None:
            return None
        contract = await self.get_status(session, upload_id)
        if contract is None:
            log.warning("contracts.draft_no_contract upload_id=%s", upload_id)
            return None

        # Load the Document to get body_markdown
        from app.models import Document
        from sqlalchemy import select as _select
        doc_res = await session.execute(
            _select(Document).where(Document.id == artifact_id)
        )
        doc = doc_res.scalar_one_or_none()
        if doc is not None and doc.body_markdown:
            try:
                draft_key = f"contracts/{upload_id}/raw/draft.md"
                _write_blob(draft_key, doc.body_markdown.encode("utf-8"))
                # Append to uploaded_files manifest
                manifest = list(contract.uploaded_files or [])
                manifest.append({
                    "filename": "draft.md",
                    "kind": "md",
                    "size_bytes": len(doc.body_markdown.encode("utf-8")),
                    "extraction_status": "ok",
                    "extraction_summary": "AI-drafted contract markdown",
                    "minio_key": draft_key,
                })
                contract.uploaded_files = manifest
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "contracts.draft_blob_write_failed upload_id=%s err=%s",
                    upload_id, exc,
                )

        contract.draft_artifact_id = artifact_id
        contract.status = "drafted"
        contract.updated_at = _utcnow()

        await audit_svc.record_event(
            session,
            event_type="contract.draft_approved",
            actor=actor,
            approval_item_id=None,
            payload={
                "upload_id": upload_id,
                "contract_id": contract.id,
                "draft_artifact_id": artifact_id,
            },
        )
        await session.commit()
        return contract


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
