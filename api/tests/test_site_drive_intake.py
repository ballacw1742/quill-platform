"""Sprint 2 — Drive-folder document intake reports honest per-document status."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services import site_drive_intake as intake_svc
from tests.conftest import auth_h

SITE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
FOLDER_URL = "https://drive.google.com/drive/folders/1pol5ejMMepLYwY1siVPfGjhk4vqSsZt5"


@pytest.fixture
def fake_datasite(monkeypatch):
    from app.routes import sites as sites_module

    async def _fake(method: str, path: str, **kwargs):
        if path == f"/sites/{SITE_ID}":
            return {"site_id": SITE_ID, "documents": []}
        raise HTTPException(status_code=404, detail="site not found")

    monkeypatch.setattr(sites_module, "_datasite_request", _fake)


# ── unit: folder ID parsing ──────────────────────────────────────────────────

def test_parse_folder_id():
    assert intake_svc.parse_folder_id(FOLDER_URL) == "1pol5ejMMepLYwY1siVPfGjhk4vqSsZt5"
    assert intake_svc.parse_folder_id("https://x.com/?id=abc123defgh") == "abc123defgh"
    assert intake_svc.parse_folder_id("not a url") is None


# ── endpoint behavior ────────────────────────────────────────────────────────

async def test_intake_requires_auth(client, fake_datasite):
    r = await client.post(
        f"/v1/sites/{SITE_ID}/documents/drive",
        json={"drive_folder_url": FOLDER_URL},
    )
    assert r.status_code == 401


async def test_intake_bad_url_422(client, owner_token, fake_datasite):
    _, tok = owner_token
    r = await client.post(
        f"/v1/sites/{SITE_ID}/documents/drive",
        json={"drive_folder_url": "nope"},
        headers=auth_h(tok),
    )
    assert r.status_code == 422


async def test_intake_listing_failure_is_honest(client, owner_token, fake_datasite, monkeypatch):
    """When Drive can't be listed, the API must say failed — not 'queued'."""
    _, tok = owner_token

    def _boom(folder_id):
        raise RuntimeError("Drive list failed: folder not shared with service account")

    monkeypatch.setattr(intake_svc, "list_folder_files", _boom)

    r = await client.post(
        f"/v1/sites/{SITE_ID}/documents/drive",
        json={"drive_folder_url": FOLDER_URL},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert "Drive list failed" in body["error"]
    assert body["documents"] == []
    assert "queued" not in str(body)


async def test_intake_per_document_status(client, owner_token, fake_datasite, monkeypatch):
    _, tok = owner_token

    files = [
        {"file_id": "f1", "filename": "Phase 1 ESA.pdf", "mime_type": "application/pdf", "size": 100},
        {"file_id": "f2", "filename": "model.xlsm", "mime_type": "application/vnd.ms-excel.sheet.macroEnabled.12", "size": 200},
        {"file_id": "f3", "filename": "Geotech Report.pdf", "mime_type": "application/pdf", "size": 300},
    ]
    monkeypatch.setattr(intake_svc, "list_folder_files", lambda folder_id: files)

    def _fake_download(file_id, mime_type, out_path):
        if file_id == "f3":
            raise RuntimeError("download failed: permission denied")
        with open(out_path, "wb") as fh:
            fh.write(b"%PDF-1.4 fake")

    monkeypatch.setattr(intake_svc, "_drive_download", _fake_download)

    uploaded: list[str] = []

    async def _fake_upload(site_id, filename, content, doc_type):
        uploaded.append(filename)
        return {"doc_id": "x", "filename": filename}

    async def _fake_analysis(site_id, folder_url):
        return {"documents_imported": 1}

    async def _fake_fetch(site_id):
        return [{"filename": "Phase 1 ESA.pdf", "summary": "an ESA", "key_findings": ["ok"]}]

    monkeypatch.setattr(intake_svc, "upload_to_datasite", _fake_upload)
    monkeypatch.setattr(intake_svc, "run_datasite_analysis", _fake_analysis)
    monkeypatch.setattr(intake_svc, "fetch_site_documents", _fake_fetch)

    r = await client.post(
        f"/v1/sites/{SITE_ID}/documents/drive",
        json={"drive_folder_url": FOLDER_URL},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed_with_errors"
    by_name = {d["filename"]: d for d in body["documents"]}
    assert by_name["Phase 1 ESA.pdf"]["status"] == "indexed"
    assert by_name["Phase 1 ESA.pdf"]["doc_type"] == "phase1_esa"
    assert by_name["model.xlsm"]["status"] == "skipped"
    assert by_name["Geotech Report.pdf"]["status"] == "failed"
    assert "permission denied" in by_name["Geotech Report.pdf"]["detail"]
    assert uploaded == ["Phase 1 ESA.pdf"]

    # GET returns the persisted latest intake for the UI.
    r = await client.get(f"/v1/sites/{SITE_ID}/documents/drive", headers=auth_h(tok))
    assert r.status_code == 200
    got = r.json()
    assert got["status"] == "completed_with_errors"
    assert len(got["documents"]) == 3

    # An audit event was chained for the intake.
    r = await client.get("/v1/audit", headers=auth_h(tok))
    if r.status_code == 200:
        types = [e.get("event_type") for e in (r.json() if isinstance(r.json(), list) else r.json().get("items", []))]
        assert "site.drive_intake" in types


async def test_intake_status_none_when_never_run(client, owner_token, fake_datasite):
    _, tok = owner_token
    r = await client.get(f"/v1/sites/{SITE_ID}/documents/drive", headers=auth_h(tok))
    assert r.status_code == 200
    assert r.json()["status"] == "none"
