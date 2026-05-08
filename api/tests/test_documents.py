"""Documents service tests \u2014 Phase D.1.

Covers:
- Direct service create_from_approval
- list with filters
- LIKE-based search (SQLite test path)
- get-by-id
- markdown export
- end-to-end execute hook: create approval \u2192 approve \u2192 document appears
- Audit event recorded
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.enums import ApprovalStatus, Lane
from app.models import ApprovalItem, AuditLogEntry, Document
from app.services import approvals as approvals_svc
from app.services.documents import (
    DOCUMENT_PUBLISHED_EVENT,
    DocumentsService,
)
from tests.conftest import agent_h, auth_h


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
def _publish_payload(
    *,
    workflow: str = "status_update.publish",
    artifact_id: str = "artifact-doc-1",
    title: str = "Weekly Status \u2014 Project Atlas",
    summary: str = "Critical-path slipping by 2 days; mitigation in flight.",
    body: str = "# Weekly Status\n\nProject Atlas is **2 days** behind plan.\n",
    artifact_type: str = "status_update",
    agent_id: str = "rfi-triage",
    lane: int = 2,
    tags: list[str] | None = None,
) -> dict:
    return {
        "agent_id": agent_id,
        "agent_version": "0.1.0",
        "workflow": workflow,
        "lane": lane,
        "priority": "normal",
        "target_system": "drive",
        "agent_confidence": 0.91,
        "payload": {
            "proposed_action": {"kind": "publish_artifact"},
            "artifact": {
                "id": artifact_id,
                "artifact_type": artifact_type,
                "title": title,
                "summary": summary,
                "body_markdown": body,
                "agent_display_name": "Status Update Author",
                "tags": tags or ["weekly", "atlas"],
            },
        },
        "source_artifacts": [],
        "citations": [],
    }


# ---------------------------------------------------------------------------
# Service-level: create_from_approval
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_create_from_approval(session_maker):
    svc = DocumentsService()

    async with session_maker() as session:
        approval = await approvals_svc.create_approval(
            session,
            payload=_publish_payload(artifact_id="art-create-1", lane=Lane.SINGLE.value),
            actor="agent:test",
        )
        # Lane 2 created pending; we exercise the service directly here.
        doc = await svc.create_from_approval(session, approval, actor="charles")
        await session.commit()

        assert doc.id
        assert doc.artifact_id == "art-create-1"
        assert doc.artifact_type == "status_update"
        assert doc.title.startswith("Weekly Status")
        assert "Project Atlas" in doc.body_markdown
        assert doc.agent_id == "rfi-triage"
        assert doc.approved_by == "charles"
        assert doc.approval_id == approval.id
        assert doc.minio_path and doc.minio_path.startswith("documents/")
        assert "weekly" in (doc.tags or [])

    # Idempotency: calling again with the same artifact_id returns the existing row.
    async with session_maker() as session:
        approval = (
            await session.execute(select(ApprovalItem).limit(1))
        ).scalar_one()
        again = await svc.create_from_approval(session, approval, actor="charles")
        assert again.artifact_id == "art-create-1"


# ---------------------------------------------------------------------------
# Service-level: list with filters + search
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_list_and_search(session_maker):
    svc = DocumentsService()

    async with session_maker() as session:
        # Two different artifact types, two different agents.
        a1 = await approvals_svc.create_approval(
            session,
            payload=_publish_payload(
                artifact_id="art-list-1",
                title="Atlas Status May 8",
                summary="Crew shortage; rework on level 3 slab.",
                body="# Atlas\nCrew shortage. Rework on level 3 slab. More text here.",
                artifact_type="status_update",
                agent_id="rfi-triage",
            ),
            actor="agent:test",
        )
        a2 = await approvals_svc.create_approval(
            session,
            payload=_publish_payload(
                workflow="knowledge_entry.publish",
                artifact_id="art-list-2",
                title="MEP rework SOP",
                summary="How to file a change order for MEP rework.",
                body="# MEP Rework SOP\n\n1. File change order.\n2. Notify GC.\n",
                artifact_type="knowledge_entry",
                agent_id="coordinator",
            ),
            actor="agent:test",
        )
        await svc.create_from_approval(session, a1, actor="charles")
        await svc.create_from_approval(session, a2, actor="charles")
        await session.commit()

    async with session_maker() as session:
        # No filters: 2 results.
        docs, total = await svc.list(session)
        assert total == 2
        assert {d.artifact_id for d in docs} == {"art-list-1", "art-list-2"}

        # Filter by artifact_type.
        docs, total = await svc.list(session, artifact_type="knowledge_entry")
        assert total == 1
        assert docs[0].artifact_id == "art-list-2"

        # Filter by agent_id.
        docs, total = await svc.list(session, agent_id="rfi-triage")
        assert total == 1
        assert docs[0].agent_id == "rfi-triage"

        # Search via list q= (LIKE fallback on SQLite).
        docs, total = await svc.list(session, q="MEP")
        assert total == 1
        assert docs[0].artifact_id == "art-list-2"

        # Dedicated search() path \u2014 SQLite returns score=None, snippet hint.
        hits, total_hits = await svc.search(session, "rework")
        assert total_hits >= 1
        ids = [d.id for (d, _, _) in hits]
        # Both rows mention "rework" in body or summary.
        assert len(ids) >= 1


# ---------------------------------------------------------------------------
# Service-level: get + export
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_get_and_export_md(session_maker):
    svc = DocumentsService()

    async with session_maker() as session:
        approval = await approvals_svc.create_approval(
            session,
            payload=_publish_payload(artifact_id="art-exp-1"),
            actor="agent:test",
        )
        doc = await svc.create_from_approval(session, approval, actor="charles")
        await session.commit()
        doc_id = doc.id

    async with session_maker() as session:
        got = await svc.get(session, doc_id)
        assert got is not None and got.id == doc_id

        body, ctype, filename = await svc.export(session, doc_id, fmt="md")
        assert b"Project Atlas" in body
        assert ctype.startswith("text/markdown")
        assert filename.endswith(".md")

        # PDF/DOCX are stubbed but must not raise.
        body2, _, fn2 = await svc.export(session, doc_id, fmt="pdf")
        assert b"stubbed" in body2
        assert fn2.endswith(".pdf.md")


# ---------------------------------------------------------------------------
# Execute hook: end-to-end via HTTP
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_execute_hook_publishes_document(client, owner_token, session_maker):
    user_id, token = owner_token

    # Agent submits a Lane-2 publish_artifact approval.
    payload = _publish_payload(
        artifact_id="e2e-art-1",
        title="E2E Status Update",
        body="# E2E\n\nAll systems nominal.",
    )
    r = await client.post("/v1/approvals", json=payload, headers=agent_h())
    assert r.status_code == 201, r.text
    aid = r.json()["id"]

    # Owner approves \u2014 this fires execute_approval which fires the doc hook.
    r = await client.post(
        f"/v1/approvals/{aid}/decide",
        json={"decision": "approve", "auth_assertion": "dev"},
        headers=auth_h(token),
    )
    assert r.status_code == 200, r.text
    decided = r.json()
    assert decided["status"] == "executed"
    assert decided["execution_result"] == "success"
    assert (decided.get("external_ref") or "").startswith("document:")
    document_id = decided["external_ref"].split("document:")[1]

    # Document is now retrievable via the API.
    r = await client.get("/v1/documents", headers=auth_h(token))
    assert r.status_code == 200
    page = r.json()
    assert page["total"] >= 1
    assert any(d["artifact_id"] == "e2e-art-1" for d in page["items"])

    r = await client.get(f"/v1/documents/{document_id}", headers=auth_h(token))
    assert r.status_code == 200
    full = r.json()
    assert full["title"] == "E2E Status Update"
    assert "All systems nominal" in full["body_markdown"]
    assert full["approval_id"] == aid

    # Audit chain has document.published with the document_id.
    async with session_maker() as session:
        rows = (
            await session.execute(
                select(AuditLogEntry).where(AuditLogEntry.approval_item_id == aid)
            )
        ).scalars().all()
        types = [e.event_type for e in rows]
        assert DOCUMENT_PUBLISHED_EVENT in types
        published = next(e for e in rows if e.event_type == DOCUMENT_PUBLISHED_EVENT)
        assert published.payload.get("document_id") == document_id
        assert published.payload.get("artifact_id") == "e2e-art-1"
        # And the executed event records the doc id too.
        executed = next(e for e in rows if e.event_type == "approval.executed")
        assert executed.payload.get("document_id") == document_id


# ---------------------------------------------------------------------------
# Lane-1 auto-execute publishes immediately
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_lane1_auto_publish(client, session_maker):
    payload = _publish_payload(
        workflow="knowledge_entry.publish",
        artifact_id="lane1-art-1",
        title="Auto-published knowledge entry",
        artifact_type="knowledge_entry",
        agent_id="coordinator",
        lane=Lane.AUTO.value,
    )
    r = await client.post("/v1/approvals", json=payload, headers=agent_h())
    assert r.status_code == 201, r.text
    body = r.json()
    # Lane 1 auto-executes inside create_approval.
    assert body["status"] == "executed"
    assert (body.get("external_ref") or "").startswith("document:")

    async with session_maker() as session:
        docs = (
            await session.execute(
                select(Document).where(Document.artifact_id == "lane1-art-1")
            )
        ).scalars().all()
        assert len(docs) == 1
        assert docs[0].artifact_type == "knowledge_entry"
        assert docs[0].approved_by  # set to the actor


# ---------------------------------------------------------------------------
# Routes: search + admin reindex
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_routes_search_and_reindex(client, owner_token):
    _, token = owner_token

    # Seed two Lane-1 docs (auto-publish).
    r = await client.post(
        "/v1/approvals",
        json=_publish_payload(
            artifact_id="rt-1",
            title="Quill Documents launch plan",
            body="Plan covers Phase D rollout.",
            lane=Lane.AUTO.value,
        ),
        headers=agent_h(),
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/v1/approvals",
        json=_publish_payload(
            workflow="knowledge_entry.publish",
            artifact_id="rt-2",
            title="Submittal review SOP",
            body="Steps for reviewing a submittal.",
            artifact_type="knowledge_entry",
            agent_id="coordinator",
            lane=Lane.AUTO.value,
        ),
        headers=agent_h(),
    )
    assert r.status_code == 201, r.text

    # Search hits.
    r = await client.get("/v1/documents/search?q=submittal", headers=auth_h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["q"] == "submittal"
    assert body["total"] >= 1
    assert any("Submittal" in h["title"] for h in body["items"])

    # Admin reindex.
    import os

    r = await client.post(
        "/v1/admin/documents/reindex",
        headers={"X-Admin": os.environ["AGENT_SHARED_SECRET"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["reindexed"] >= 2
    assert body["backend"] in {"postgres-tsvector", "sqlite-like"}


# ---------------------------------------------------------------------------
# Auth gate: anonymous request to /v1/documents must 401
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_documents_requires_auth(client):
    r = await client.get("/v1/documents")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Drive link: returns pending=True until async export populates it
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_drive_link_pending(client, owner_token):
    _, token = owner_token
    r = await client.post(
        "/v1/approvals",
        json=_publish_payload(artifact_id="dl-1", lane=Lane.AUTO.value),
        headers=agent_h(),
    )
    aid = r.json()["id"]
    doc_id = r.json()["external_ref"].split("document:")[1]
    r = await client.get(f"/v1/documents/{doc_id}/drive_link", headers=auth_h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["pending"] is True
    assert body["url"] is None
    # Touch aid so the lint sees it used.
    assert aid
