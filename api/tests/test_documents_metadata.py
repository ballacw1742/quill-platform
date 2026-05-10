"""Tests for Sprint G.7 — Document.meta column and DocumentOut.metadata field.

Covers:
- create_from_approval populates Document.meta from the artifact payload.
- Round-trip: write metadata → read it back → matches original.
- DocumentOut serializes metadata; DocumentSummary does not include metadata.
- Backfill script is idempotent.
- Size-cap truncation stores a marker dict rather than overflowing.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.enums import Lane
from app.models import ApprovalItem, Document
from app.schemas import DocumentOut, DocumentSummary
from app.services import approvals as approvals_svc
from app.services.documents import DocumentsService
from tests.conftest import agent_h, auth_h


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cost_schedule_payload(
    *,
    artifact_id: str = "art-meta-1",
    title: str = "Cost & Schedule Package v1",
    lane: int = Lane.SINGLE.value,
) -> dict:
    """Approval payload that mimics a real cost_schedule_package artifact."""
    return {
        "agent_id": "estimator-v1",
        "agent_version": "0.2.0",
        "workflow": "coordinator_artifact.publish",
        "lane": lane,
        "priority": "normal",
        "target_system": "drive",
        "agent_confidence": 0.85,
        "payload": {
            "proposed_action": {"kind": "publish_artifact"},
            "artifact": {
                "id": artifact_id,
                "artifact_type": "cost_schedule_package",
                "title": title,
                "summary": "AACE Class 4 estimate with L1 schedule.",
                "body_markdown": "# Cost & Schedule\n\nSee tables below.\n",
                "agent_display_name": "Estimator Agent",
                "tags": ["estimate", "aace-4"],
                "metadata": {
                    "project_label": "Test Project",
                    "aace_class": "4",
                    "estimate": {
                        "rows": [
                            {
                                "csi_section": "03 30 00",
                                "description": "Concrete",
                                "quantity": 100,
                                "unit": "CY",
                                "unit_rate_usd": 450,
                                "extended_usd": 45000,
                                "rate_source": "library_v0_1",
                                "confidence": 0.8,
                            }
                        ],
                        "subtotal_direct_usd": 45000,
                        "total_usd": 50000,
                        "indirects": [],
                    },
                    "schedule": {
                        "level": 1,
                        "activities": [
                            {
                                "id": "A001",
                                "name": "Mobilization",
                                "duration_days": 5,
                            }
                        ],
                        "total_duration_days": 5,
                        "milestones": [],
                    },
                    "cost_rows": [
                        {"csi_section": "03 30 00", "description": "Concrete"}
                    ],
                },
            },
        },
        "source_artifacts": [],
        "citations": [],
    }


# ---------------------------------------------------------------------------
# 1. create_from_approval populates metadata
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_from_approval_populates_meta(session_maker):
    """Document.meta must be set to the extracted artifact dict after create."""
    svc = DocumentsService()

    async with session_maker() as session:
        approval = await approvals_svc.create_approval(
            session,
            payload=_cost_schedule_payload(artifact_id="art-meta-create-1"),
            actor="agent:estimator",
        )
        doc = await svc.create_from_approval(session, approval, actor="charles")
        await session.commit()

        assert doc.meta is not None, "Document.meta should be set"
        assert isinstance(doc.meta, dict)
        # The full artifact payload — includes artifact_type, metadata key, etc.
        assert doc.meta.get("artifact_type") == "cost_schedule_package"
        assert "metadata" in doc.meta
        assert doc.meta["metadata"]["estimate"]["total_usd"] == 50000
        assert doc.meta["metadata"]["schedule"]["activities"][0]["id"] == "A001"


# ---------------------------------------------------------------------------
# 2. Round-trip: write → read → matches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_meta_round_trip(session_maker):
    """Write a document with metadata and verify it survives a DB round-trip."""
    svc = DocumentsService()

    async with session_maker() as session:
        approval = await approvals_svc.create_approval(
            session,
            payload=_cost_schedule_payload(artifact_id="art-meta-rt-1"),
            actor="agent:estimator",
        )
        doc = await svc.create_from_approval(session, approval, actor="charles")
        doc_id = doc.id
        await session.commit()

    # Fresh session — read back from DB.
    async with session_maker() as session:
        loaded = await session.get(Document, doc_id)
        assert loaded is not None
        assert loaded.meta is not None
        # Spot-check the nested estimate block survived the round-trip.
        assert loaded.meta["metadata"]["estimate"]["rows"][0]["csi_section"] == "03 30 00"
        assert loaded.meta["metadata"]["cost_rows"][0]["description"] == "Concrete"


# ---------------------------------------------------------------------------
# 3. DocumentOut serializes metadata; DocumentSummary does not
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_document_out_includes_metadata_summary_does_not(session_maker):
    """DocumentOut exposes metadata; DocumentSummary must not."""
    svc = DocumentsService()

    async with session_maker() as session:
        approval = await approvals_svc.create_approval(
            session,
            payload=_cost_schedule_payload(artifact_id="art-meta-schema-1"),
            actor="agent:estimator",
        )
        doc = await svc.create_from_approval(session, approval, actor="charles")
        await session.commit()

        # DocumentOut — must include metadata.
        out = DocumentOut.model_validate(doc)
        assert out.metadata is not None
        assert isinstance(out.metadata, dict)
        assert out.metadata.get("artifact_type") == "cost_schedule_package"

        # DocumentSummary — must NOT have a metadata field.
        assert not hasattr(DocumentSummary, "model_fields") or \
            "metadata" not in DocumentSummary.model_fields

        # Serialized JSON for DocumentOut must carry metadata.
        data = out.model_dump()
        assert "metadata" in data
        assert data["metadata"] is not None


# ---------------------------------------------------------------------------
# 4. Backfill script is idempotent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backfill_idempotent(session_maker):
    """Backfill logic: documents with meta already set are skipped; idempotent."""
    svc = DocumentsService()

    # 1. Create a document via the service — meta is populated.
    async with session_maker() as session:
        approval = await approvals_svc.create_approval(
            session,
            payload=_cost_schedule_payload(artifact_id="art-meta-backfill-1"),
            actor="agent:estimator",
        )
        doc = await svc.create_from_approval(session, approval, actor="charles")
        doc_id = doc.id
        await session.commit()

    # 2. Verify meta is set (not NULL).
    async with session_maker() as session:
        loaded = await session.get(Document, doc_id)
        assert loaded.meta is not None, "create_from_approval must set meta"
        first_meta = json.dumps(loaded.meta, sort_keys=True)

    # 3. Simulate the backfill WHERE clause — this row must NOT appear because
    #    its meta column is already populated.
    async with session_maker() as session:
        stmt = (
            select(Document)
            .where(Document.meta.is_(None))
            .where(Document.approval_id.isnot(None))
        )
        candidates = list((await session.execute(stmt)).scalars().all())
        assert not any(c.id == doc_id for c in candidates), (
            "backfill WHERE clause matched a doc that already has meta — not idempotent"
        )

    # 4. Data is still intact.
    async with session_maker() as session:
        loaded2 = await session.get(Document, doc_id)
        assert json.dumps(loaded2.meta, sort_keys=True) == first_meta

    # 5. Create a second doc and manually clear its meta to simulate a pre-sprint
    #    row.  Then run one backfill pass and confirm it gets populated.
    async with session_maker() as session:
        approval2 = await approvals_svc.create_approval(
            session,
            payload=_cost_schedule_payload(artifact_id="art-meta-backfill-2"),
            actor="agent:estimator",
        )
        doc2 = await svc.create_from_approval(session, approval2, actor="charles")
        doc2_id = doc2.id
        doc2_approval_id = doc2.approval_id
        await session.commit()

    # Null it out via raw SQL to bypass SQLAlchemy attribute-mapping quirks.
    from sqlalchemy import text as sa_text

    async with session_maker() as session:
        await session.execute(
            sa_text("UPDATE documents SET metadata = NULL WHERE id = :doc_id").bindparams(
                doc_id=doc2_id
            )
        )
        await session.commit()

    # Confirm it is now NULL in a fresh read.
    async with session_maker() as session:
        await session.execute(sa_text("SELECT 1"))  # ensure fresh connection
        pre = await session.get(Document, doc2_id)
        assert pre.meta is None, "raw UPDATE should have cleared meta"

    # Run one backfill pass — doc2 should get populated.
    async with session_maker() as session:
        stmt = (
            select(Document)
            .where(Document.meta.is_(None))
            .where(Document.approval_id.isnot(None))
        )
        nulls = list((await session.execute(stmt)).scalars().all())
        for d in nulls:
            appr = await session.get(ApprovalItem, d.approval_id)
            if appr:
                artifact = DocumentsService._extract_artifact(appr)
                d.meta = artifact
                await session.flush()
        await session.commit()

    async with session_maker() as session:
        filled = await session.get(Document, doc2_id)
        assert filled.meta is not None, "backfill should populate meta"

    # Run backfill again — second pass must be a no-op (no rows selected).
    async with session_maker() as session:
        stmt = (
            select(Document)
            .where(Document.meta.is_(None))
            .where(Document.approval_id.isnot(None))
        )
        second_pass = list((await session.execute(stmt)).scalars().all())
        assert not any(d.id == doc2_id for d in second_pass), (
            "second backfill pass selected an already-filled row — not idempotent"
        )


# ---------------------------------------------------------------------------
# 5. Size-cap: oversized payload stores a truncation marker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_meta_size_cap_stores_marker(session_maker, monkeypatch):
    """A payload that exceeds 256 KB must be replaced by a truncation marker."""
    svc = DocumentsService()

    # Monkeypatch _extract_artifact to return a huge dict.
    big_artifact = {
        "id": "art-huge-1",
        "artifact_type": "cost_schedule_package",
        "title": "Huge",
        "summary": "",
        "body_markdown": "",
        "filler": "x" * (300 * 1024),  # 300 KB of junk
    }
    monkeypatch.setattr(
        DocumentsService,
        "_extract_artifact",
        staticmethod(lambda _approval: big_artifact),
    )

    async with session_maker() as session:
        approval = await approvals_svc.create_approval(
            session,
            payload=_cost_schedule_payload(artifact_id="art-huge-1"),
            actor="agent:estimator",
        )
        doc = await svc.create_from_approval(session, approval, actor="charles")
        await session.commit()

        assert doc.meta is not None
        assert doc.meta.get("_truncated") is True
        assert "reason" in doc.meta


# ---------------------------------------------------------------------------
# 6. HTTP layer: GET /v1/documents/{id} returns metadata in response body
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_get_document_returns_metadata(client, session_maker, owner_token):
    """The REST endpoint must include the metadata field in its JSON response."""
    svc = DocumentsService()
    _, token = owner_token

    async with session_maker() as session:
        approval = await approvals_svc.create_approval(
            session,
            payload=_cost_schedule_payload(artifact_id="art-meta-api-1"),
            actor="agent:estimator",
        )
        doc = await svc.create_from_approval(session, approval, actor="charles")
        doc_id = doc.id
        await session.commit()

    resp = await client.get(
        f"/v1/documents/{doc_id}",
        headers=auth_h(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "metadata" in body
    assert body["metadata"] is not None
    assert body["metadata"].get("artifact_type") == "cost_schedule_package"
