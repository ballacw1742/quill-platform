"""One-shot backfill: populate Document.meta from the linked ApprovalItem.

For each Document whose ``metadata`` column is NULL and which has an
``approval_id``, look up the corresponding ApprovalItem, extract the
artifact payload via DocumentsService._extract_artifact, and write it
back onto the Document.

Usage::

    # from repo root (venv activated):
    .venv/bin/python -m api.scripts.backfill_document_metadata

Idempotent: documents that already have a non-NULL metadata are skipped.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

# ---------------------------------------------------------------------------
# Ensure the api/ package is importable when run as a module from repo root.
# ---------------------------------------------------------------------------
_here = os.path.dirname(__file__)
_api_root = os.path.abspath(os.path.join(_here, "..", ".."))
if _api_root not in sys.path:
    sys.path.insert(0, _api_root)

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models import ApprovalItem, Document  # noqa: E402
from app.services.documents import DocumentsService  # noqa: E402

log = logging.getLogger("quill.backfill_document_metadata")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

_META_CAP_BYTES = 256 * 1024


async def _run() -> None:
    settings = get_settings()
    db_url = settings.DATABASE_URL

    engine = create_async_engine(db_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        # Fetch documents that have an approval_id but no metadata yet.
        stmt = (
            select(Document)
            .where(Document.meta.is_(None))
            .where(Document.approval_id.isnot(None))
        )
        result = await session.execute(stmt)
        docs = list(result.scalars().all())

        log.info("Found %d document(s) to backfill.", len(docs))

        updated = 0
        skipped = 0

        for doc in docs:
            # Fetch the corresponding approval item.
            approval = await session.get(ApprovalItem, doc.approval_id)
            if approval is None:
                log.warning(
                    "  skip doc=%s — approval_id=%s not found", doc.id, doc.approval_id
                )
                skipped += 1
                continue

            artifact = DocumentsService._extract_artifact(approval)

            # Apply the same size cap used by create_from_approval.
            try:
                serialized = json.dumps(artifact, default=str)
                if len(serialized) > _META_CAP_BYTES:
                    log.warning(
                        "  doc=%s artifact too large (%d bytes), storing truncation marker",
                        doc.id,
                        len(serialized),
                    )
                    meta_payload = {
                        "_truncated": True,
                        "reason": f"payload exceeded {_META_CAP_BYTES} bytes ({len(serialized)})",
                    }
                else:
                    meta_payload = artifact
            except Exception as exc:  # noqa: BLE001
                log.warning("  doc=%s serialize error: %s — skipping", doc.id, exc)
                skipped += 1
                continue

            doc.meta = meta_payload
            updated += 1
            log.info(
                "  updated doc=%s artifact_type=%s metadata_keys=%s",
                doc.id,
                doc.artifact_type,
                list(meta_payload.keys()) if isinstance(meta_payload, dict) else "marker",
            )

        await session.commit()

    await engine.dispose()
    log.info(
        "Backfill complete: updated=%d skipped=%d total_inspected=%d",
        updated,
        skipped,
        len(docs),
    )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
