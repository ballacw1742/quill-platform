"""Contracts Drafter API tests — Sprint Contracts.3.

Covers:
- GET  /v1/contracts/templates              (list; at least 10 items)
- GET  /v1/contracts/templates/{id}         (single; 404 on miss)
- POST /v1/contracts/draft                  (201; correct fields)
- POST /v1/contracts/{upload_id}/redraft    (201; new row with prior_contract_upload_id)
- POST /v1/contracts/{upload_id}/dispatch_draft (200 / 409 / 404)
- GET  /v1/contracts?source=drafted         (filter works)
- on_draft_approved hook                    (status flip + artifact stamp)
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

from app.models import Contract, Document
from sqlalchemy import select
from tests.conftest import auth_h

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DRAFT_REQUEST_BODY: dict[str, Any] = {
    "mode": "template",
    "contract_type": "subcontract",
    "template_id": "subcontract_standard",
    "parties": [
        {"role": "contractor", "name": "Acme GC LLC"},
        {"role": "subcontractor", "name": "Beta Framing Inc"},
    ],
    "effective_date": "2026-06-01",
    "expiration_date": None,
    "total_value_usd": 125000.0,
    "payment_terms": "Net 30",
    "scope_summary": "Framing work for Project Alpha",
    "key_terms_requested": [
        {"topic": "indemnification", "requirement": "mutual indemnification only"},
    ],
    "jurisdiction": "Ohio",
    "notes": "Standard subcontract for framing scope.",
    "prior_contract_upload_id": None,
}

# ---------------------------------------------------------------------------
# GET /v1/contracts/templates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_templates_returns_at_least_10(client):
    """List templates endpoint returns at least 10 entries with valid frontmatter."""
    resp = await client.get("/api/v1/contracts/templates", headers=auth_h())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "items" in data
    assert "total" in data
    items = data["items"]
    assert len(items) >= 10, f"Expected >= 10 templates, got {len(items)}"
    for item in items:
        assert "template_id" in item, f"Missing template_id: {item}"
        assert "contract_type" in item, f"Missing contract_type: {item}"
        assert "display_name" in item, f"Missing display_name: {item}"


@pytest.mark.asyncio
async def test_list_templates_items_match_total(client):
    resp = await client.get("/api/v1/contracts/templates", headers=auth_h())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == len(data["items"])


# ---------------------------------------------------------------------------
# GET /v1/contracts/templates/{template_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_template_found(client):
    """Single-template endpoint returns frontmatter + body."""
    # First get the list to find a real template_id
    list_resp = await client.get("/api/v1/contracts/templates", headers=auth_h())
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert items, "No templates found"

    tid = items[0]["template_id"]
    resp = await client.get(f"/api/v1/contracts/templates/{tid}", headers=auth_h())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["template_id"] == tid
    # body should be present (may be empty string but key exists)
    assert "body" in data


@pytest.mark.asyncio
async def test_get_template_not_found(client):
    """Returns 404 for unknown template_id."""
    resp = await client.get(
        "/api/v1/contracts/templates/does-not-exist-xyz", headers=auth_h()
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /v1/contracts/draft
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_draft_request_201(client):
    """Draft creation returns 201 with correct fields."""
    resp = await client.post(
        "/api/v1/contracts/draft",
        json=_DRAFT_REQUEST_BODY,
        headers=auth_h(),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["source"] == "drafted"
    assert data["status"] == "drafting"
    assert data["mode"] == "template"
    assert data["draft_request"] is not None
    assert data["draft_request"]["contract_type"] == "subcontract"
    assert "upload_id" in data


@pytest.mark.asyncio
async def test_create_draft_request_db_row(client, session_maker):
    """Draft creation persists correct Contract row to DB."""
    resp = await client.post(
        "/api/v1/contracts/draft",
        json=_DRAFT_REQUEST_BODY,
        headers=auth_h(),
    )
    assert resp.status_code == 201
    upload_id = resp.json()["upload_id"]

    async with session_maker() as s:
        result = await s.execute(
            select(Contract).where(Contract.upload_id == upload_id)
        )
        contract = result.scalar_one_or_none()
        assert contract is not None
        assert contract.source == "drafted"
        assert contract.status == "drafting"
        assert contract.mode == "template"
        assert contract.draft_request is not None
        assert contract.draft_request.get("contract_type") == "subcontract"


@pytest.mark.asyncio
async def test_create_draft_negotiated_mode(client):
    """Negotiated mode (no template_id) works too."""
    body = {**_DRAFT_REQUEST_BODY, "mode": "negotiated", "template_id": None}
    resp = await client.post(
        "/api/v1/contracts/draft",
        json=body,
        headers=auth_h(),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["mode"] == "negotiated"
    assert data["source"] == "drafted"


# ---------------------------------------------------------------------------
# POST /v1/contracts/{upload_id}/redraft
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redraft_creates_new_row(client, session_maker):
    """Redraft creates a new Contract row linked by prior_contract_upload_id."""
    # Create parent
    parent_resp = await client.post(
        "/api/v1/contracts/draft",
        json=_DRAFT_REQUEST_BODY,
        headers=auth_h(),
    )
    assert parent_resp.status_code == 201
    parent_upload_id = parent_resp.json()["upload_id"]

    # Redraft
    resp = await client.post(
        f"/api/v1/contracts/{parent_upload_id}/redraft",
        json={
            "revision_notes": "Add liquidated damages clause",
            "key_terms_overrides": [
                {"topic": "liquidated_damages", "requirement": "$500/day"},
            ],
        },
        headers=auth_h(),
    )
    assert resp.status_code == 201, resp.text
    new_upload_id = resp.json()["upload_id"]
    assert new_upload_id != parent_upload_id

    # Verify the new row has the parent reference in draft_request
    async with session_maker() as s:
        result = await s.execute(
            select(Contract).where(Contract.upload_id == new_upload_id)
        )
        new_contract = result.scalar_one_or_none()
        assert new_contract is not None
        assert new_contract.draft_request is not None
        assert new_contract.draft_request.get("prior_contract_upload_id") == parent_upload_id


@pytest.mark.asyncio
async def test_redraft_not_found(client):
    """Redraft 404 on unknown upload_id."""
    resp = await client.post(
        f"/api/v1/contracts/{uuid.uuid4()}/redraft",
        json={"revision_notes": "test"},
        headers=auth_h(),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /v1/contracts/{upload_id}/dispatch_draft
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_draft_200(client):
    """dispatch_draft returns 200 for a contract in 'drafting' status."""
    create_resp = await client.post(
        "/api/v1/contracts/draft",
        json=_DRAFT_REQUEST_BODY,
        headers=auth_h(),
    )
    assert create_resp.status_code == 201
    upload_id = create_resp.json()["upload_id"]

    resp = await client.post(
        f"/api/v1/contracts/{upload_id}/dispatch_draft",
        headers=auth_h(),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["upload_id"] == upload_id


@pytest.mark.asyncio
async def test_dispatch_draft_409_wrong_source(client):
    """dispatch_draft returns 409 when source != 'drafted'."""
    import io

    # Create an uploaded (not drafted) contract
    from app.services.contracts import service as contracts_service
    from app.db import SessionLocal

    # Use upload endpoint
    upload_resp = await client.post(
        "/api/v1/contracts/upload",
        files={"files": ("test.txt", io.BytesIO(b"contract text"), "text/plain")},
        data={"project_label": "Test Project"},
        headers=auth_h(),
    )
    assert upload_resp.status_code == 201
    upload_id = upload_resp.json()["upload_id"]

    resp = await client.post(
        f"/api/v1/contracts/{upload_id}/dispatch_draft",
        headers=auth_h(),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_dispatch_draft_404(client):
    """dispatch_draft returns 404 for unknown upload_id."""
    resp = await client.post(
        f"/api/v1/contracts/{uuid.uuid4()}/dispatch_draft",
        headers=auth_h(),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dispatch_draft_409_wrong_status(client, session_maker):
    """dispatch_draft returns 409 when status is 'drafted' (already done)."""
    # Create a draft contract and manually set it to 'drafted'
    create_resp = await client.post(
        "/api/v1/contracts/draft",
        json=_DRAFT_REQUEST_BODY,
        headers=auth_h(),
    )
    assert create_resp.status_code == 201
    upload_id = create_resp.json()["upload_id"]

    async with session_maker() as s:
        result = await s.execute(
            select(Contract).where(Contract.upload_id == upload_id)
        )
        contract = result.scalar_one()
        contract.status = "drafted"
        await s.commit()

    resp = await client.post(
        f"/api/v1/contracts/{upload_id}/dispatch_draft",
        headers=auth_h(),
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /v1/contracts?source=drafted  (list filter)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_filter_source_drafted(client):
    """Listing with source=drafted returns only drafted contracts."""
    import io

    # Create one drafted contract
    draft_resp = await client.post(
        "/api/v1/contracts/draft",
        json=_DRAFT_REQUEST_BODY,
        headers=auth_h(),
    )
    assert draft_resp.status_code == 201
    drafted_id = draft_resp.json()["upload_id"]

    # Create one uploaded contract
    upload_resp = await client.post(
        "/api/v1/contracts/upload",
        files={"files": ("test.txt", io.BytesIO(b"contract text"), "text/plain")},
        data={"project_label": "Uploaded"},
        headers=auth_h(),
    )
    assert upload_resp.status_code == 201

    resp = await client.get(
        "/api/v1/contracts?source=drafted",
        headers=auth_h(),
    )
    assert resp.status_code == 200
    data = resp.json()
    items = data["items"]
    assert all(item["source"] == "drafted" for item in items), (
        f"Expected all drafted, got: {[i['source'] for i in items]}"
    )
    upload_ids = [item["upload_id"] for item in items]
    assert drafted_id in upload_ids


# ---------------------------------------------------------------------------
# on_draft_approved hook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_draft_approved_flips_status(session_maker):
    """on_draft_approved stamps draft_artifact_id and flips status to 'drafted'."""
    from app.services.contracts import service as contracts_service
    from app.schemas import ContractDraftRequest

    req = ContractDraftRequest(**_DRAFT_REQUEST_BODY)

    async with session_maker() as s:
        # Create a fake user
        from app.models import User
        from app.enums import UserRole
        from app.security import hash_password

        user = User(
            email=f"drafter-test-{uuid.uuid4()}@example.com",
            display_name="Test User",
            role=UserRole.OWNER.value,
            password_hash=hash_password("password123"),
        )
        s.add(user)
        await s.flush()

        contract = await contracts_service.create_draft_request(s, request=req, user=user)
        upload_id = contract.upload_id

        # Create a fake Document artifact
        doc = Document(
            artifact_id=str(uuid.uuid4()),
            artifact_type="contract_draft",
            title="Draft Subcontract",
            summary="AI-drafted subcontract.",
            body_markdown="# Draft Contract\n\nThis is the draft.",
            agent_id="contract-drafter",
            agent_display_name="Contract Drafter",
        )
        s.add(doc)
        await s.flush()

        # Call the hook
        result = await contracts_service.on_draft_approved(
            s,
            upload_id=upload_id,
            artifact_id=doc.id,
            actor="test-user",
        )

        assert result is not None
        assert result.status == "drafted"
        assert result.draft_artifact_id == doc.id


@pytest.mark.asyncio
async def test_on_draft_approved_appends_uploaded_files(session_maker):
    """on_draft_approved appends a 'md' entry to uploaded_files."""
    from app.services.contracts import service as contracts_service
    from app.schemas import ContractDraftRequest
    from app.models import User
    from app.enums import UserRole
    from app.security import hash_password

    req = ContractDraftRequest(**_DRAFT_REQUEST_BODY)

    async with session_maker() as s:
        user = User(
            email=f"drafter-test2-{uuid.uuid4()}@example.com",
            display_name="Test User 2",
            role=UserRole.OWNER.value,
            password_hash=hash_password("password123"),
        )
        s.add(user)
        await s.flush()

        contract = await contracts_service.create_draft_request(s, request=req, user=user)
        upload_id = contract.upload_id

        doc = Document(
            artifact_id=str(uuid.uuid4()),
            artifact_type="contract_draft",
            title="Draft NDA",
            summary="AI-drafted NDA.",
            body_markdown="# NDA\n\nMutual non-disclosure agreement.",
            agent_id="contract-drafter",
            agent_display_name="Contract Drafter",
        )
        s.add(doc)
        await s.flush()

        await contracts_service.on_draft_approved(
            s,
            upload_id=upload_id,
            artifact_id=doc.id,
            actor="test-user",
        )

        # Re-fetch to verify
        from sqlalchemy import select as _select
        result = await s.execute(
            _select(Contract).where(Contract.upload_id == upload_id)
        )
        updated = result.scalar_one()
        kinds = [f.get("kind") for f in (updated.uploaded_files or [])]
        assert "md" in kinds, f"Expected 'md' in kinds, got: {kinds}"
