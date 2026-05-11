"""Contracts Review API tests — Sprint Contracts.2.

Covers:
- POST /v1/contracts/{upload_id}/dispatch_review  (200 / 404 / 409)
- POST /v1/contracts/{upload_id}/interpret        (200 / 400 / 404 / 409)
- GET  /v1/contracts/{upload_id}/reviews          (200 / 404)
- GET  /v1/contracts/{upload_id}/interpretations  (200 / 404)

All tests run against a per-test in-memory SQLite DB.
Agent invocations are stubbed to avoid live LLM calls.
"""

from __future__ import annotations

import unittest.mock as mock
from typing import Any

import pytest

from app.models import Contract
from sqlalchemy import select
from tests.conftest import auth_h

_CANONICAL_DISCLAIMER = (
    "AI-generated analysis. This is not legal advice. "
    "Review with qualified counsel before relying on it for any binding decision."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _tiny_txt() -> bytes:
    return (
        b"SUBCONTRACT AGREEMENT\n\n"
        b"Section 14 - INDEMNIFICATION\n"
        b"Subcontractor shall indemnify Contractor from all claims.\n"
    )


def _noop_coro():
    """Return a coroutine that immediately returns None (for monkeypatching)."""
    async def _inner(*args, **kwargs):
        return None
    return _inner()


_MOCK_EXTRACTED_FIELDS: dict[str, Any] = {
    "artifact_type": "contract_extraction",
    "contract_type": "subcontract",
    "parties": [{"role": "owner", "name": "Acme Construction"}],
    "total_value_usd": 100000,
    "notable_clauses": [
        {
            "section": "Section 14",
            "heading": "Indemnification",
            "verbatim": "Subcontractor shall indemnify Contractor from all claims.",
        }
    ],
    "disclaimer": _CANONICAL_DISCLAIMER,
}

_MOCK_INTERPRET_OUTPUT: dict[str, Any] = {
    "question": "What does the indemnity obligate me to?",
    "answer": "Under Section 14, you are required to defend and indemnify the contractor.",
    "supporting_clauses": [
        {
            "verbatim": "Subcontractor shall indemnify Contractor from all claims.",
            "location": "Section 14",
            "why_relevant": "This is the full indemnification clause.",
        }
    ],
    "confidence": 0.9,
    "caveats": [{"caveat": "Ohio broad-form indemnity may be unenforceable."}],
    "disclaimer": _CANONICAL_DISCLAIMER,
}


async def _upload_and_set(
    client,
    token: str,
    session_maker,
    tmp_path,
    monkeypatch,
    *,
    status: str = "extracted",
    extracted_fields: dict | None = None,
    review_artifact_id: str | None = None,
) -> str:
    """Upload a contract and directly set DB fields for testing."""
    import app.services.contracts as _csvc
    monkeypatch.setenv("CONTRACTS_BLOB_PATH", str(tmp_path / "blobs"))
    monkeypatch.setattr(_csvc.service, "_run_extraction_async", lambda uid: _noop_coro())

    resp = await client.post(
        "/v1/contracts/upload",
        files=[("files", ("contract.txt", _tiny_txt(), "text/plain"))],
        data={"project_label": "Test Contract"},
        headers=auth_h(token),
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["upload_id"]

    # Directly set DB fields for test control
    async with session_maker() as s:
        res = await s.execute(select(Contract).where(Contract.upload_id == upload_id))
        c = res.scalar_one()
        c.status = status
        if extracted_fields is not None:
            c.extracted_fields = extracted_fields
        if review_artifact_id is not None:
            c.review_artifact_id = review_artifact_id
        await s.commit()

    return upload_id


# ---------------------------------------------------------------------------
# dispatch_review — happy path and error cases
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_review_200(client, owner_token, session_maker, tmp_path, monkeypatch):
    _, token = owner_token
    upload_id = await _upload_and_set(
        client, token, session_maker, tmp_path, monkeypatch,
        status="extracted",
        extracted_fields=_MOCK_EXTRACTED_FIELDS,
    )
    resp = await client.post(
        f"/v1/contracts/{upload_id}/dispatch_review",
        headers=auth_h(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["upload_id"] == upload_id
    assert "audit_hash" in data


@pytest.mark.asyncio
async def test_dispatch_review_404(client, owner_token):
    _, token = owner_token
    resp = await client.post(
        "/v1/contracts/nonexistent-id/dispatch_review",
        headers=auth_h(token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dispatch_review_409_no_extraction(client, owner_token, session_maker, tmp_path, monkeypatch):
    """409 when extracted_fields is NULL."""
    _, token = owner_token
    upload_id = await _upload_and_set(
        client, token, session_maker, tmp_path, monkeypatch,
        status="extracted",
        extracted_fields=None,
    )
    resp = await client.post(
        f"/v1/contracts/{upload_id}/dispatch_review",
        headers=auth_h(token),
    )
    assert resp.status_code == 409
    assert "extraction" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_dispatch_review_409_wrong_status(client, owner_token, session_maker, tmp_path, monkeypatch):
    """409 when status is 'extracting' (not in reviewable set)."""
    _, token = owner_token
    upload_id = await _upload_and_set(
        client, token, session_maker, tmp_path, monkeypatch,
        status="extracting",
        extracted_fields=_MOCK_EXTRACTED_FIELDS,
    )
    resp = await client.post(
        f"/v1/contracts/{upload_id}/dispatch_review",
        headers=auth_h(token),
    )
    assert resp.status_code == 409
    assert "status" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_dispatch_review_idempotent(client, owner_token, session_maker, tmp_path, monkeypatch):
    """Dispatching twice succeeds both times (idempotent)."""
    _, token = owner_token
    upload_id = await _upload_and_set(
        client, token, session_maker, tmp_path, monkeypatch,
        status="extracted",
        extracted_fields=_MOCK_EXTRACTED_FIELDS,
    )
    resp1 = await client.post(
        f"/v1/contracts/{upload_id}/dispatch_review",
        headers=auth_h(token),
    )
    resp2 = await client.post(
        f"/v1/contracts/{upload_id}/dispatch_review",
        headers=auth_h(token),
    )
    assert resp1.status_code == 200
    assert resp2.status_code == 200


# ---------------------------------------------------------------------------
# interpret — happy path (stubbed agent) and error cases
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_interpret_200_stubbed(client, owner_token, session_maker, tmp_path, monkeypatch):
    _, token = owner_token
    upload_id = await _upload_and_set(
        client, token, session_maker, tmp_path, monkeypatch,
        status="extracted",
        extracted_fields=_MOCK_EXTRACTED_FIELDS,
    )

    mock_run = mock.MagicMock()
    mock_run.output = _MOCK_INTERPRET_OUTPUT.copy()
    mock_run.error = None
    mock_run.validation_ok = True
    mock_run.validation_errors = []
    mock_run.model_used = "claude-sonnet-4-6"

    with mock.patch(
        "runtime.agent.Agent.run",
        new=mock.AsyncMock(return_value=mock_run),
    ):
        resp = await client.post(
            f"/v1/contracts/{upload_id}/interpret",
            json={"question": "What does the indemnity obligate me to?"},
            headers=auth_h(token),
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["contract_upload_id"] == upload_id
    assert len(data["answer"]) > 0
    assert data["disclaimer"] == _CANONICAL_DISCLAIMER
    assert "interpretation_id" in data
    assert data["confidence"] == 0.9


@pytest.mark.asyncio
async def test_interpret_400_empty_question(client, owner_token, session_maker, tmp_path, monkeypatch):
    _, token = owner_token
    upload_id = await _upload_and_set(
        client, token, session_maker, tmp_path, monkeypatch,
        status="extracted",
        extracted_fields=_MOCK_EXTRACTED_FIELDS,
    )
    resp = await client.post(
        f"/v1/contracts/{upload_id}/interpret",
        json={"question": ""},
        headers=auth_h(token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_interpret_400_question_too_long(client, owner_token, session_maker, tmp_path, monkeypatch):
    _, token = owner_token
    upload_id = await _upload_and_set(
        client, token, session_maker, tmp_path, monkeypatch,
        status="extracted",
        extracted_fields=_MOCK_EXTRACTED_FIELDS,
    )
    resp = await client.post(
        f"/v1/contracts/{upload_id}/interpret",
        json={"question": "x" * 501},
        headers=auth_h(token),
    )
    assert resp.status_code == 400
    assert "too long" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_interpret_404(client, owner_token):
    _, token = owner_token
    resp = await client.post(
        "/v1/contracts/nonexistent/interpret",
        json={"question": "What does this mean?"},
        headers=auth_h(token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_interpret_409_no_extraction(client, owner_token, session_maker, tmp_path, monkeypatch):
    _, token = owner_token
    upload_id = await _upload_and_set(
        client, token, session_maker, tmp_path, monkeypatch,
        status="uploaded",
        extracted_fields=None,
    )
    resp = await client.post(
        f"/v1/contracts/{upload_id}/interpret",
        json={"question": "What does this mean?"},
        headers=auth_h(token),
    )
    assert resp.status_code == 409
    assert "extraction" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_interpret_disclaimer_always_present(client, owner_token, session_maker, tmp_path, monkeypatch):
    """Disclaimer must be in response regardless of agent output."""
    _, token = owner_token
    upload_id = await _upload_and_set(
        client, token, session_maker, tmp_path, monkeypatch,
        status="extracted",
        extracted_fields=_MOCK_EXTRACTED_FIELDS,
    )
    # Agent output without disclaimer field — service should add it.
    output_no_disclaimer = {k: v for k, v in _MOCK_INTERPRET_OUTPUT.items() if k != "disclaimer"}

    mock_run = mock.MagicMock()
    mock_run.output = output_no_disclaimer
    mock_run.error = None
    mock_run.validation_ok = True
    mock_run.validation_errors = []
    mock_run.model_used = "claude-sonnet-4-6"

    with mock.patch(
        "runtime.agent.Agent.run",
        new=mock.AsyncMock(return_value=mock_run),
    ):
        resp = await client.post(
            f"/v1/contracts/{upload_id}/interpret",
            json={"question": "Does the disclaimer appear?"},
            headers=auth_h(token),
        )

    assert resp.status_code == 200
    assert resp.json()["disclaimer"] == _CANONICAL_DISCLAIMER


# ---------------------------------------------------------------------------
# reviews list
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reviews_list_200_empty(client, owner_token, session_maker, tmp_path, monkeypatch):
    _, token = owner_token
    upload_id = await _upload_and_set(
        client, token, session_maker, tmp_path, monkeypatch,
        status="extracted",
        extracted_fields=_MOCK_EXTRACTED_FIELDS,
    )
    resp = await client.get(
        f"/v1/contracts/{upload_id}/reviews",
        headers=auth_h(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_reviews_list_404(client, owner_token):
    _, token = owner_token
    resp = await client.get(
        "/v1/contracts/nonexistent/reviews",
        headers=auth_h(token),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# interpretations list
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_interpretations_list_200_empty(client, owner_token, session_maker, tmp_path, monkeypatch):
    _, token = owner_token
    upload_id = await _upload_and_set(
        client, token, session_maker, tmp_path, monkeypatch,
        status="extracted",
        extracted_fields=_MOCK_EXTRACTED_FIELDS,
    )
    resp = await client.get(
        f"/v1/contracts/{upload_id}/interpretations",
        headers=auth_h(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_interpretations_list_404(client, owner_token):
    _, token = owner_token
    resp = await client.get(
        "/v1/contracts/nonexistent/interpretations",
        headers=auth_h(token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_interpretations_persist_after_interpret(client, owner_token, session_maker, tmp_path, monkeypatch):
    """After a successful interpret call, the Q&A appears in the list."""
    _, token = owner_token
    upload_id = await _upload_and_set(
        client, token, session_maker, tmp_path, monkeypatch,
        status="extracted",
        extracted_fields=_MOCK_EXTRACTED_FIELDS,
    )

    mock_run = mock.MagicMock()
    mock_run.output = _MOCK_INTERPRET_OUTPUT.copy()
    mock_run.error = None
    mock_run.validation_ok = True
    mock_run.validation_errors = []
    mock_run.model_used = "claude-sonnet-4-6"

    with mock.patch(
        "runtime.agent.Agent.run",
        new=mock.AsyncMock(return_value=mock_run),
    ):
        post_resp = await client.post(
            f"/v1/contracts/{upload_id}/interpret",
            json={"question": "What does the indemnity obligate me to?"},
            headers=auth_h(token),
        )

    assert post_resp.status_code == 200

    list_resp = await client.get(
        f"/v1/contracts/{upload_id}/interpretations",
        headers=auth_h(token),
    )
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1
    item = data["items"][0]
    assert item["contract_upload_id"] == upload_id
    assert item["disclaimer"] == _CANONICAL_DISCLAIMER
