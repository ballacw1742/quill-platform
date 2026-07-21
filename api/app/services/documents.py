"""Documents service \u2014 Phase D.1.

Owns persistence, blob storage, search, export, and Drive sync for
artifacts produced by PM agents and approved for publication.

Design notes:
- The blob layer ("MinIO") is currently a local filesystem mirror under
  `settings.DOCUMENTS_BLOB_PATH`. A real MinIO/S3 backend will plug in
  here without changing call-sites; the path key
  (`documents/<YYYY>/<MM>/<artifact_id>.md`) is already S3-friendly.
- Drive export is best-effort and async: we kick off `gog drive upload`
  in the background and write `drive_url` back to the row when it
  returns. Document creation is never blocked on it.
- Search uses Postgres tsvector on prod and a LIKE fallback on SQLite
  (dev). The route layer doesn't care which.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ApprovalItem, Document
from app.services import audit as audit_svc

log = logging.getLogger("quill.documents")

_settings = get_settings()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ARTIFACT_PUBLISH_WORKFLOWS: frozenset[str] = frozenset(
    {
        "status_update.publish",
        "coordinator_artifact.publish",
        "pm_analysis.publish",
        "comms_draft.publish",
        "knowledge_entry.publish",
    }
)
"""Workflows whose approvals should produce a Document on execute."""

PUBLISH_ACTION_KIND = "publish_artifact"
"""payload.proposed_action.kind value that maps to publishing an artifact."""

DOCUMENT_PUBLISHED_EVENT = "document.published"

# Allow only [a-z0-9_-]; map artifact_type strings to UI-friendly buckets if needed.
_safe_re = re.compile(r"[^a-z0-9_-]+")


def _slugify(s: str) -> str:
    return _safe_re.sub("-", (s or "").strip().lower()).strip("-") or "document"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _blob_root() -> Path:
    """Resolve the local-mode blob root directory (idempotent mkdir)."""
    raw = getattr(_settings, "DOCUMENTS_BLOB_PATH", None) or os.environ.get(
        "DOCUMENTS_BLOB_PATH", "./_local_documents"
    )
    p = Path(raw).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _blob_key(artifact_id: str, when: datetime) -> str:
    return f"documents/{when:%Y}/{when:%m}/{artifact_id}.md"


def _is_postgres(session: AsyncSession) -> bool:
    return session.bind.dialect.name == "postgresql"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class DocumentsService:
    """High-level Documents API. Stateless; takes a session per call."""

    # ---- Create ----------------------------------------------------------
    async def create_from_approval(
        self,
        session: AsyncSession,
        approval: ApprovalItem,
        *,
        actor: str = "system",
    ) -> Document:
        """Create a Document from an approved artifact.

        Idempotent on artifact_id: if a document already exists for
        approval.payload.artifact.id we return it untouched.
        """
        artifact = self._extract_artifact(approval)
        artifact_id = str(artifact.get("id") or approval.id)

        # Idempotency: same artifact_id never produces two documents.
        existing = await session.execute(
            select(Document).where(Document.artifact_id == artifact_id)
        )
        prior = existing.scalar_one_or_none()
        if prior is not None:
            return prior

        title = self._coerce_str(artifact.get("title"), fallback=approval.workflow)[:255]
        summary = self._coerce_str(artifact.get("summary"))[:511]
        body_markdown = self._coerce_str(
            artifact.get("body_markdown") or artifact.get("body") or artifact.get("content")
        )
        artifact_type = self._coerce_str(
            artifact.get("artifact_type") or self._derive_artifact_type(approval),
            fallback="document",
        )[:63]
        agent_id = approval.agent_id
        agent_display_name = self._coerce_str(
            artifact.get("agent_display_name"), fallback=agent_id
        )[:127]
        tags = artifact.get("tags") or []
        if not isinstance(tags, list):
            tags = [str(tags)]
        tags = [str(t) for t in tags][:64]

        approved_at = approval.executed_at or _utcnow()
        approved_by = actor

        # Sanity-cap the artifact payload at 256 KB. If it's larger we store
        # a small marker dict so callers can detect the truncation.
        _META_CAP_BYTES = 256 * 1024
        try:
            _serialized = json.dumps(artifact, default=str)
            if len(_serialized) > _META_CAP_BYTES:
                log.warning(
                    "documents.meta_truncated artifact_id=%s size=%d cap=%d",
                    artifact_id,
                    len(_serialized),
                    _META_CAP_BYTES,
                )
                meta_payload: dict[str, Any] | None = {
                    "_truncated": True,
                    "reason": f"payload exceeded {_META_CAP_BYTES} bytes ({len(_serialized)})",
                }
            else:
                meta_payload = artifact
        except Exception as exc:  # noqa: BLE001
            log.warning("documents.meta_serialize_failed artifact_id=%s err=%s", artifact_id, exc)
            meta_payload = None

        # Sprint 4: contracts.list_reviews looks reviews up via
        # meta.contract_upload_id + meta.artifact, so contract_review
        # documents store the wrapped shape instead of the bare artifact.
        if (
            (approval.workflow or "") == "contract_review.publish"
            and isinstance(meta_payload, dict)
            and not meta_payload.get("_truncated")
        ):
            _p = approval.payload or {}
            _cuid = _p.get("contract_upload_id") or (
                (_p.get("context") or {}).get("contract_upload_id")
            )
            meta_payload = {
                "artifact": meta_payload,
                "contract_upload_id": _cuid,
            }

        doc = Document(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            title=title or "(untitled)",
            summary=summary,
            body_markdown=body_markdown,
            agent_id=agent_id,
            agent_display_name=agent_display_name,
            created_at=_utcnow(),
            approved_at=approved_at,
            approved_by=approved_by,
            approval_id=approval.id,
            tags=tags,
            minio_path=_blob_key(artifact_id, approved_at),
            meta=meta_payload,
        )
        session.add(doc)
        await session.flush()

        # Write markdown body to the blob layer (best-effort: a write failure
        # logs and continues; the row is the system of record).
        try:
            self._write_blob(doc.minio_path, body_markdown)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "documents.blob_write_failed artifact_id=%s err=%s", artifact_id, exc
            )

        # Audit event.
        entry = await audit_svc.record_event_with_mirror(
            session,
            event_type=DOCUMENT_PUBLISHED_EVENT,
            actor=approved_by,
            approval_item_id=approval.id,
            payload={
                "document_id": doc.id,
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "agent_id": agent_id,
                "title": doc.title,
                "minio_path": doc.minio_path,
            },
        )
        log.info(
            "documents.published id=%s artifact_id=%s agent=%s audit_hash=%s",
            doc.id,
            artifact_id,
            agent_id,
            entry.hash,
        )

        # Schedule async Drive export (best-effort; never blocks).
        try:
            asyncio.get_event_loop().create_task(
                self._drive_export_async(doc.id, doc.title, body_markdown, approved_at)
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("documents.drive_schedule_failed id=%s err=%s", doc.id, exc)

        return doc

    # ---- Create (direct, non-approval artifacts) -------------------------
    async def create_site_report(
        self,
        session: AsyncSession,
        *,
        site_id: str,
        title: str,
        summary: str,
        body_markdown: str,
        meta: dict[str, Any] | None,
        project_id: str | None = None,
        actor: str = "system",
    ) -> Document:
        """File a DataSite Site Evaluation Report as a first-class Document.

        Not approval-gated (the report is a rendering of an already-approved
        evaluation, not a new system-of-record write). Idempotent on
        artifact_id = 'site-report:{site_id}': re-filing updates the existing
        row in place (new evaluations refresh the report) rather than
        duplicating. Tagged 'site-research' + 'datasite-report' and carries
        site_id/project_id in tags + meta so /documents filtering can find it.
        """
        artifact_id = f"site-report:{site_id}"
        tags = ["site-research", "datasite-report", f"site:{site_id}"]
        if project_id:
            tags.append(f"project:{project_id}")

        meta_payload = dict(meta or {})
        meta_payload.setdefault("site_id", site_id)
        if project_id:
            meta_payload.setdefault("project_id", project_id)

        now = _utcnow()
        existing = await session.execute(
            select(Document).where(Document.artifact_id == artifact_id)
        )
        doc = existing.scalar_one_or_none()
        if doc is not None:
            # Refresh in place (idempotent update on re-accept / re-score).
            doc.title = (title or doc.title)[:255]
            doc.summary = (summary or "")[:511]
            doc.body_markdown = body_markdown
            doc.tags = tags
            doc.meta = meta_payload
            doc.created_at = now
            try:
                self._write_blob(doc.minio_path, body_markdown)
            except Exception as exc:  # noqa: BLE001
                log.warning("documents.blob_write_failed artifact_id=%s err=%s", artifact_id, exc)
            await session.flush()
            return doc

        doc = Document(
            artifact_id=artifact_id,
            artifact_type="site_evaluation_report",
            title=(title or "DataSite Site Evaluation Report")[:255],
            summary=(summary or "")[:511],
            body_markdown=body_markdown,
            agent_id="datasite_site_evaluator",
            agent_display_name="DataSite Site Evaluator",
            created_at=now,
            approved_at=now,
            approved_by=actor,
            approval_id=None,
            tags=tags,
            minio_path=_blob_key(artifact_id, now),
            meta=meta_payload,
        )
        session.add(doc)
        await session.flush()
        try:
            self._write_blob(doc.minio_path, body_markdown)
        except Exception as exc:  # noqa: BLE001
            log.warning("documents.blob_write_failed artifact_id=%s err=%s", artifact_id, exc)

        try:
            await audit_svc.record_event_with_mirror(
                session,
                event_type=DOCUMENT_PUBLISHED_EVENT,
                actor=actor,
                approval_item_id=None,
                payload={
                    "document_id": doc.id,
                    "artifact_id": artifact_id,
                    "artifact_type": "site_evaluation_report",
                    "site_id": site_id,
                    "title": doc.title,
                },
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("documents.site_report_audit_failed site_id=%s err=%s", site_id, exc)

        log.info("documents.site_report_filed id=%s site_id=%s", doc.id, site_id)
        return doc

    # ---- Read ------------------------------------------------------------
    async def get(self, session: AsyncSession, doc_id: str) -> Document | None:
        return await session.get(Document, doc_id)

    async def list(
        self,
        session: AsyncSession,
        *,
        artifact_type: str | None = None,
        agent_id: str | None = None,
        since: datetime | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Document], int]:
        stmt = select(Document).order_by(Document.created_at.desc())
        if artifact_type:
            stmt = stmt.where(Document.artifact_type == artifact_type)
        if agent_id:
            stmt = stmt.where(Document.agent_id == agent_id)
        if since:
            stmt = stmt.where(Document.created_at >= since)
        if q:
            stmt = self._apply_search_filter(session, stmt, q)

        # Cheap count (small dataset; cardinality of `documents` is bounded by
        # approved artifacts, not raw events).
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar_one() or 0

        page = await session.execute(stmt.offset(offset).limit(limit))
        return list(page.scalars().all()), int(total)

    async def search(
        self,
        session: AsyncSession,
        q: str,
        *,
        limit: int = 20,
    ) -> tuple[list[tuple[Document, float | None, str | None]], int]:
        """Full-text search.

        Returns a list of `(doc, score, snippet)` tuples plus a total count.
        score/snippet are populated on Postgres; SQLite returns None.
        """
        if not q or not q.strip():
            return [], 0

        if _is_postgres(session):
            return await self._search_postgres(session, q, limit=limit)
        return await self._search_sqlite(session, q, limit=limit)

    # ---- Export ----------------------------------------------------------
    async def export(
        self,
        session: AsyncSession,
        doc_id: str,
        *,
        fmt: str = "md",
    ) -> tuple[bytes, str, str]:
        """Return (bytes, content_type, filename) for the requested export.

        v0.1: only `md` is fully supported. `pdf`/`docx` return a stub
        body so the frontend can wire its UI; KNOWN_ISSUES tracks the
        real implementation.
        """
        doc = await self.get(session, doc_id)
        if doc is None:
            raise LookupError(f"document {doc_id} not found")

        safe_title = _slugify(doc.title)[:80] or "document"

        if fmt == "md":
            body = doc.body_markdown or ""
            return (
                body.encode("utf-8"),
                "text/markdown; charset=utf-8",
                f"{safe_title}.md",
            )
        if fmt in {"pdf", "docx"}:
            stub = (
                f"# {doc.title}\n\n"
                f"_This export format ({fmt}) is stubbed in v0.1. "
                f"The Markdown body follows verbatim:_\n\n"
                f"{doc.body_markdown or ''}"
            ).encode("utf-8")
            ctype = "text/markdown; charset=utf-8"
            return stub, ctype, f"{safe_title}.{fmt}.md"
        raise ValueError(f"unsupported export format: {fmt}")

    # ---- Drive link ------------------------------------------------------
    async def drive_link(self, session: AsyncSession, doc_id: str) -> dict[str, Any]:
        doc = await self.get(session, doc_id)
        if doc is None:
            raise LookupError(f"document {doc_id} not found")
        return {"url": doc.drive_url, "pending": doc.drive_url is None}

    # ---- Reindex (admin) -------------------------------------------------
    async def reindex(self, session: AsyncSession) -> dict[str, Any]:
        """Rebuild the FTS index.

        On Postgres this is essentially a no-op (the tsvector column is
        STORED + auto-maintained), but we still ANALYZE the table.
        On SQLite there's no real index to rebuild; we return a count of
        rows so callers can see the operation completed.
        """
        if _is_postgres(session):
            try:
                await session.execute(text("ANALYZE documents"))
            except Exception as exc:  # noqa: BLE001
                log.warning("documents.reindex.analyze_failed err=%s", exc)
            backend = "postgres-tsvector"
        else:
            backend = "sqlite-like"

        total = (
            await session.execute(select(func.count()).select_from(Document))
        ).scalar_one() or 0
        await session.commit()
        return {"ok": True, "reindexed": int(total), "backend": backend}

    # ---- internals -------------------------------------------------------
    @staticmethod
    def _coerce_str(value: Any, *, fallback: str = "") -> str:
        if value is None:
            return fallback
        if isinstance(value, str):
            return value
        try:
            return str(value)
        except Exception:  # noqa: BLE001
            return fallback

    @staticmethod
    def _extract_artifact(approval: ApprovalItem) -> dict[str, Any]:
        """Pull the artifact dict out of an approval payload, tolerantly."""
        payload = approval.payload or {}
        # Conventional shape: payload.artifact = {...}
        artifact = payload.get("artifact")
        if isinstance(artifact, dict):
            return artifact
        # Sometimes the proposed_action.payload itself is the artifact.
        proposed = payload.get("proposed_action") or {}
        if isinstance(proposed, dict):
            inner = proposed.get("artifact") or proposed.get("payload")
            if isinstance(inner, dict):
                return inner
        # Fall back to the entire payload as the artifact body.
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _derive_artifact_type(approval: ApprovalItem) -> str:
        """Best-effort artifact_type inference from workflow."""
        wf = (approval.workflow or "").lower()
        if "status_update" in wf:
            return "status_update"
        if "coordinator" in wf:
            return "coordinator_artifact"
        if "pm_analysis" in wf or "analysis" in wf:
            return "pm_analysis"
        if "comms" in wf or "comm_draft" in wf:
            return "comms_draft"
        if "knowledge" in wf:
            return "knowledge_entry"
        if "raci" in wf:
            return "coordinator_artifact"
        if "sop" in wf:
            return "knowledge_entry"
        return "document"

    @staticmethod
    def _write_blob(rel_key: str, body: str) -> Path:
        root = _blob_root()
        target = (root / rel_key).resolve()
        # Defensive: ensure target is under root (no traversal via crafted artifact ids).
        if not str(target).startswith(str(root)):
            raise ValueError(f"blob path escapes root: {rel_key}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body or "", encoding="utf-8")
        return target

    def _apply_search_filter(self, session: AsyncSession, stmt, q: str):
        if _is_postgres(session):
            # Use plainto_tsquery for safety; the column is GENERATED so the
            # comparison is straightforward.
            return stmt.where(
                text(
                    "documents.search_vector @@ plainto_tsquery('english', :q)"
                ).bindparams(q=q)
            )
        like = f"%{q}%"
        return stmt.where(
            or_(
                Document.title.ilike(like),
                Document.summary.ilike(like),
                Document.body_markdown.ilike(like),
            )
        )

    async def _search_postgres(
        self, session: AsyncSession, q: str, *, limit: int
    ) -> tuple[list[tuple[Document, float | None, str | None]], int]:
        # Score with ts_rank_cd; snippet with ts_headline for nice UI.
        sql = text(
            """
            SELECT id,
                   ts_rank_cd(search_vector, plainto_tsquery('english', :q)) AS score,
                   ts_headline('english', coalesce(body_markdown, summary), plainto_tsquery('english', :q),
                               'MaxFragments=1, MaxWords=20, MinWords=5') AS snippet
            FROM documents
            WHERE search_vector @@ plainto_tsquery('english', :q)
            ORDER BY score DESC, created_at DESC
            LIMIT :limit
            """
        ).bindparams(q=q, limit=limit)
        rows = (await session.execute(sql)).all()
        ids = [r.id for r in rows]
        if not ids:
            return [], 0
        # Hydrate full Document rows in one trip.
        full = await session.execute(select(Document).where(Document.id.in_(ids)))
        by_id = {d.id: d for d in full.scalars().all()}
        results = [
            (by_id[r.id], float(r.score), r.snippet) for r in rows if r.id in by_id
        ]
        return results, len(results)

    async def _search_sqlite(
        self, session: AsyncSession, q: str, *, limit: int
    ) -> tuple[list[tuple[Document, float | None, str | None]], int]:
        like = f"%{q}%"
        stmt = (
            select(Document)
            .where(
                or_(
                    Document.title.ilike(like),
                    Document.summary.ilike(like),
                    Document.body_markdown.ilike(like),
                )
            )
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        docs = list((await session.execute(stmt)).scalars().all())
        results: list[tuple[Document, float | None, str | None]] = [
            (d, None, _excerpt(d.body_markdown or d.summary, q)) for d in docs
        ]
        return results, len(results)

    async def _drive_export_async(
        self, doc_id: str, title: str, body_markdown: str, when: datetime
    ) -> None:
        """Best-effort Google Drive upload via the gog CLI.

        Failure modes are all logged and swallowed; the document is the
        system of record regardless of Drive availability.
        """
        if not getattr(_settings, "DOCUMENTS_DRIVE_ENABLED", False):
            log.debug("documents.drive_export_disabled doc_id=%s", doc_id)
            return

        gog_bin = os.environ.get("GOG_BIN", "gog")
        # Write a temp markdown file the CLI can ingest.
        tmp_root = _blob_root() / "_drive_uploads"
        tmp_root.mkdir(parents=True, exist_ok=True)
        tmp_file = tmp_root / f"{doc_id}.md"
        try:
            tmp_file.write_text(body_markdown or "", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log.warning("documents.drive_tmp_write_failed doc_id=%s err=%s", doc_id, exc)
            return

        drive_path = f"/Quill/Documents/{when:%Y}/{when:%m}/{title}.gdoc"
        cmd = (
            f"{shlex.quote(gog_bin)} drive upload --title {shlex.quote(title)} "
            f"--target {shlex.quote(drive_path)} {shlex.quote(str(tmp_file))}"
        )
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except Exception as exc:  # noqa: BLE001
            log.warning("documents.drive_upload_failed doc_id=%s err=%s", doc_id, exc)
            return

        if proc.returncode != 0:
            log.warning(
                "documents.drive_upload_nonzero doc_id=%s rc=%s stderr=%s",
                doc_id,
                proc.returncode,
                stderr.decode("utf-8", errors="replace")[:512],
            )
            return

        # Parse the URL out of stdout (best-effort; gog implementations vary).
        url: str | None = None
        out = stdout.decode("utf-8", errors="replace")
        m = re.search(r"https?://docs\.google\.com/[^\s]+", out)
        if m:
            url = m.group(0)
        if not url:
            log.info("documents.drive_url_not_in_output doc_id=%s out=%s", doc_id, out[:256])
            return

        # Stamp the URL back on the row in a fresh session.
        from app.db import SessionLocal

        try:
            async with SessionLocal() as s:
                d = await s.get(Document, doc_id)
                if d is not None:
                    d.drive_url = url
                    await s.commit()
                    log.info("documents.drive_url_stored doc_id=%s url=%s", doc_id, url)
        except Exception as exc:  # noqa: BLE001
            log.warning("documents.drive_url_store_failed doc_id=%s err=%s", doc_id, exc)


def _excerpt(body: str | None, q: str, *, span: int = 80) -> str | None:
    if not body or not q:
        return None
    idx = body.lower().find(q.lower())
    if idx < 0:
        return body[: span * 2]
    start = max(0, idx - span)
    end = min(len(body), idx + len(q) + span)
    pre = "\u2026" if start > 0 else ""
    suf = "\u2026" if end < len(body) else ""
    return f"{pre}{body[start:end]}{suf}"


# Module-level singleton for convenience.
service = DocumentsService()


__all__ = [
    "DocumentsService",
    "service",
    "ARTIFACT_PUBLISH_WORKFLOWS",
    "PUBLISH_ACTION_KIND",
    "DOCUMENT_PUBLISHED_EVENT",
]
