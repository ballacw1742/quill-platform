"""Drive-folder document intake for Sites.

Honest pipeline:
  1. List the Drive folder (recursively, bounded) via the Google Drive API v3,
     authenticated with the Quill Drive service account
     (DRIVE_SERVICE_ACCOUNT_JSON). The folder must be shared with the service
     account's email (see below).
  2. Download each supported file locally (Drive files.get / export).
  3. Upload each file's bytes to DataSite's per-site document endpoint.
  4. Ask DataSite to run its document-analyst over the folder, then read
     the site record back and mark which documents were actually analyzed.

Every document gets a real status: indexed | uploaded | skipped | failed.
The intake run itself is completed | completed_with_errors | failed.
No step ever reports success it can't demonstrate.

AUTH — production service-account path (replaces the earlier `gog` CLI demo
identity, which was not available in Cloud Run). Drive access uses the same
service account as deliverable authoring (DRIVE_SERVICE_ACCOUNT_JSON,
SA email quill-drive-author@<project>.iam.gserviceaccount.com). For the
intake to read a folder, that folder must be shared with the SA email
(Viewer is sufficient). Credential building mirrors
``app/services/drive_author.py`` (_build_credentials).

The google client libraries (google-auth, google-api-python-client) are
declared api dependencies (pyproject.toml). If they are somehow absent, the
listing step raises a clear RuntimeError and the intake honestly reports
`failed`.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import tempfile
from typing import Any

import httpx

log = logging.getLogger("quill.site_drive_intake")

DATASITE_URL = os.environ.get(
    "DATASITE_URL", "https://datasite-agents-894031978246.us-central1.run.app"
)

# Read-only Drive access is all the intake needs.
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Google-native mimetypes that must be exported rather than downloaded, and
# the export mimetype we request for each.
_GOOGLE_EXPORT_MIMES = {
    "application/vnd.google-apps.document": (
        "application/pdf",
        ".pdf",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/pdf",
        ".pdf",
    ),
}

SUPPORTED_EXTS = {".pdf", ".docx", ".txt", ".md"}
# Image site docs (site plans, parcel maps, aerials, scans) analyzed by
# DataSite's document-analyst vision pass.
SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
SUPPORTED_IMAGE_MIMES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
FOLDER_MIME = "application/vnd.google-apps.folder"
MAX_FILES = 25
MAX_DEPTH = 2

_DOC_TYPE_PATTERNS: list[tuple[str, str]] = [
    (r"phase\s*1|phase\s*i\b|esa", "phase1_esa"),
    (r"geotech", "geotech"),
    (r"\bloi\b|letter of intent|utility", "utility_loi"),
    (r"title", "title"),
    (r"apprais", "appraisal"),
    (r"\bom\b|offering", "om"),
    (r"survey|alta", "survey"),
]


def parse_folder_id(url: str) -> str | None:
    """Extract a Drive folder ID from a URL (or accept a bare ID)."""
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", url.strip()):
        return url.strip()
    return None


def guess_doc_type(filename: str) -> str:
    low = filename.lower()
    for pattern, doc_type in _DOC_TYPE_PATTERNS:
        if re.search(pattern, low):
            return doc_type
    return "other"


# ---------------------------------------------------------------------------
# Google Drive API v3 client (service-account auth).
# Module-level wrappers so tests can monkeypatch them.
# ---------------------------------------------------------------------------
def _build_drive_service():
    """Build a read-only Drive API client from DRIVE_SERVICE_ACCOUNT_JSON.

    Mirrors app/services/drive_author.py:_build_credentials. Raises
    RuntimeError (not ImportError/ValueError) so callers surface a single,
    honest failure mode.
    """
    try:
        from google.oauth2 import service_account  # type: ignore[import]
        from googleapiclient.discovery import build  # type: ignore[import]
    except ImportError as exc:  # pragma: no cover - libs are declared deps
        raise RuntimeError(
            "google client libraries not installed "
            "(google-auth, google-api-python-client)"
        ) from exc

    # Imported lazily to avoid a hard config dependency at import time.
    from app.config import get_settings

    sa_json_str = (get_settings().DRIVE_SERVICE_ACCOUNT_JSON or "").strip()
    if not sa_json_str:
        raise RuntimeError(
            "DRIVE_SERVICE_ACCOUNT_JSON is not configured; cannot read Drive folder"
        )
    try:
        sa_info = json.loads(sa_json_str)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"DRIVE_SERVICE_ACCOUNT_JSON is not valid JSON: {exc}") from exc

    creds = service_account.Credentials.from_service_account_info(
        sa_info, scopes=_DRIVE_SCOPES
    )
    # cache_discovery=False avoids a noisy warning + file cache in Cloud Run.
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _drive_ls(folder_id: str) -> list[dict[str, Any]]:
    """List immediate children of a Drive folder via the Drive API.

    Returns entries shaped like the previous gog output
    ({id, name, mimeType, size}) so downstream code is unchanged.
    Supports both My Drive and Shared Drives. Raises RuntimeError on failure.
    """
    svc = _build_drive_service()
    out: list[dict[str, Any]] = []
    page_token: str | None = None
    try:
        while True:
            resp = (
                svc.files()
                .list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    fields="nextPageToken, files(id, name, mimeType, size)",
                    pageSize=100,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
                )
                .execute()
            )
            out.extend(resp.get("files", []) or [])
            page_token = resp.get("nextPageToken")
            if not page_token or len(out) >= 100:
                break
    except Exception as exc:  # noqa: BLE001 - google raises varied error types
        raise RuntimeError(f"Drive list failed: {str(exc)[:300]}") from exc
    return out


def _drive_download(file_id: str, mime_type: str, out_path: str) -> None:
    """Download (or export) one Drive file to out_path. Raises on failure."""
    try:
        from googleapiclient.http import MediaIoBaseDownload  # type: ignore[import]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("google-api-python-client not installed") from exc

    svc = _build_drive_service()
    try:
        if mime_type in _GOOGLE_EXPORT_MIMES:
            export_mime, _ext = _GOOGLE_EXPORT_MIMES[mime_type]
            request = svc.files().export_media(fileId=file_id, mimeType=export_mime)
        else:
            request = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _status, done = downloader.next_chunk()
        data = buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"download failed: {str(exc)[:300]}") from exc

    if not data:
        raise RuntimeError("download produced no file")
    with open(out_path, "wb") as fh:
        fh.write(data)


def list_folder_files(folder_id: str) -> list[dict[str, Any]]:
    """Recursively list files (bounded depth/count). Each entry:
    {file_id, filename, mime_type, size}."""
    out: list[dict[str, Any]] = []

    def _walk(fid: str, depth: int) -> None:
        if len(out) >= MAX_FILES:
            return
        for f in _drive_ls(fid):
            if len(out) >= MAX_FILES:
                return
            mime = f.get("mimeType", "")
            if mime == FOLDER_MIME:
                if depth < MAX_DEPTH:
                    _walk(f["id"], depth + 1)
                continue
            out.append({
                "file_id": f.get("id"),
                "filename": f.get("name", "unknown"),
                "mime_type": mime,
                "size": int(f.get("size") or 0),
            })

    _walk(folder_id, 0)
    return out


# ---------------------------------------------------------------------------
# DataSite calls (module-level so tests can monkeypatch them)
# ---------------------------------------------------------------------------
async def upload_to_datasite(
    site_id: str, filename: str, content: bytes, doc_type: str
) -> dict[str, Any]:
    """Upload one document's bytes to DataSite. Raises on failure."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{DATASITE_URL}/sites/{site_id}/documents",
            params={"doc_type": doc_type},
            files=[("file", (filename, content, "application/octet-stream"))],
        )
        resp.raise_for_status()
        return resp.json()


async def run_datasite_analysis(site_id: str, folder_url: str) -> dict[str, Any]:
    """Ask DataSite's document analyst to index the Drive folder. Raises on failure."""
    async with httpx.AsyncClient(timeout=280) as client:
        resp = await client.post(
            f"{DATASITE_URL}/sites/{site_id}/documents/drive",
            json={"folder_url": folder_url},
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_site_documents(site_id: str) -> list[dict[str, Any]]:
    """Fetch the site record's documents list from DataSite."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{DATASITE_URL}/sites/{site_id}")
        resp.raise_for_status()
        return resp.json().get("documents", []) or []


# ---------------------------------------------------------------------------
# Intake orchestration
# ---------------------------------------------------------------------------
def _is_supported(filename: str, mime_type: str) -> bool:
    if mime_type == "application/pdf":
        return True
    # Google-native docs/sheets/slides are supported via export (see
    # _GOOGLE_EXPORT_MIMES); they often carry no filename extension.
    if mime_type in _GOOGLE_EXPORT_MIMES:
        return True
    # Images (site plans, maps, scans) — analyzed via the vision pass.
    if mime_type in SUPPORTED_IMAGE_MIMES:
        return True
    ext = os.path.splitext(filename)[1].lower()
    return ext in SUPPORTED_EXTS or ext in SUPPORTED_IMAGE_EXTS


async def run_intake(site_id: str, folder_url: str) -> dict[str, Any]:
    """Run the full intake. Returns:
    {status, error, documents: [{file_id, filename, mime_type, size,
                                 doc_type, status, detail}]}
    Never raises for per-document problems; only returns an overall
    `failed` status if nothing could even be listed.
    """
    folder_id = parse_folder_id(folder_url)
    if not folder_id:
        return {
            "status": "failed",
            "error": f"could not extract a Drive folder ID from: {folder_url}",
            "documents": [],
        }

    # 1. List
    try:
        files = await asyncio.to_thread(list_folder_files, folder_id)
    except RuntimeError as exc:
        log.warning("drive intake list failed site=%s err=%s", site_id, exc)
        return {"status": "failed", "error": str(exc), "documents": []}

    if not files:
        return {
            "status": "failed",
            "error": "Drive folder is empty or not accessible to the intake account",
            "documents": [],
        }

    # 2+3. Download + upload each supported file
    docs: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="quill_drive_intake_") as tmpdir:
        for f in files:
            # Google-native files export to a different format (e.g. a Google
            # Doc -> PDF); reflect the resulting extension in the filename so
            # DataSite stores/recognizes it correctly.
            upload_name = f["filename"]
            if f["mime_type"] in _GOOGLE_EXPORT_MIMES:
                _export_mime, ext = _GOOGLE_EXPORT_MIMES[f["mime_type"]]
                if not upload_name.lower().endswith(ext):
                    upload_name = f"{upload_name}{ext}"

            entry = {
                "file_id": f["file_id"],
                "filename": upload_name,
                "mime_type": f["mime_type"],
                "size": f["size"],
                "doc_type": guess_doc_type(upload_name),
            }
            if not _is_supported(f["filename"], f["mime_type"]):
                entry["status"] = "skipped"
                entry["detail"] = f"unsupported type ({f['mime_type']})"
                docs.append(entry)
                continue

            local_path = os.path.join(tmpdir, f"{f['file_id']}_{os.path.basename(upload_name)}")
            try:
                await asyncio.to_thread(
                    _drive_download, f["file_id"], f["mime_type"], local_path
                )
            except RuntimeError as exc:
                entry["status"] = "failed"
                entry["detail"] = f"Drive download failed: {exc}"
                docs.append(entry)
                continue

            try:
                with open(local_path, "rb") as fh:
                    content = fh.read()
                await upload_to_datasite(site_id, upload_name, content, entry["doc_type"])
                entry["status"] = "uploaded"
                entry["detail"] = "stored in DataSite; analysis pending"
            except Exception as exc:  # noqa: BLE001
                entry["status"] = "failed"
                entry["detail"] = f"DataSite upload failed: {str(exc)[:200]}"
            docs.append(entry)

    # 4. Best-effort analyst pass, then verify what actually got analyzed.
    analysis_error: str | None = None
    try:
        await run_datasite_analysis(site_id, folder_url)
    except Exception as exc:  # noqa: BLE001
        analysis_error = f"DataSite analyst pass unavailable: {str(exc)[:200]}"
        log.warning("drive intake analysis failed site=%s err=%s", site_id, exc)

    try:
        site_docs = await fetch_site_documents(site_id)
        analyzed_names = {
            d.get("filename")
            for d in site_docs
            if d.get("summary") or d.get("key_findings") or d.get("extracted_data")
        }
        for entry in docs:
            if entry.get("status") == "uploaded" and entry["filename"] in analyzed_names:
                entry["status"] = "indexed"
                entry["detail"] = "analyzed by DataSite document analyst"
    except Exception as exc:  # noqa: BLE001
        log.warning("drive intake verify failed site=%s err=%s", site_id, exc)

    ok = [d for d in docs if d["status"] in ("indexed", "uploaded")]
    bad = [d for d in docs if d["status"] == "failed"]
    if ok and not bad:
        status = "completed"
    elif ok:
        status = "completed_with_errors"
    else:
        status = "failed"

    return {"status": status, "error": analysis_error, "documents": docs}
