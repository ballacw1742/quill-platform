"""Drive-folder document intake for Sites — Sprint 2.

Honest pipeline:
  1. List the Drive folder (recursively, bounded) with the `gog` CLI
     (OAuth'd as the demo Drive identity on this host).
  2. Download each supported file locally.
  3. Upload each file's bytes to DataSite's per-site document endpoint.
  4. Ask DataSite to run its document-analyst over the folder, then read
     the site record back and mark which documents were actually analyzed.

Every document gets a real status: indexed | uploaded | skipped | failed.
The intake run itself is completed | completed_with_errors | failed.
No step ever reports success it can't demonstrate.

A GCP service account for Drive access is explicitly post-demo; the `gog`
CLI path is the intended demo identity (see task brief). When `gog` is not
available (e.g. Cloud Run), the listing step fails and the intake honestly
reports `failed` with the underlying error.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
from typing import Any

import httpx

log = logging.getLogger("quill.site_drive_intake")

GOG_BIN = os.environ.get("GOG_BIN", "gog")
DRIVE_ACCOUNT = os.environ.get("DRIVE_INTAKE_ACCOUNT", "white.1284@gmail.com")
DATASITE_URL = os.environ.get(
    "DATASITE_URL", "https://datasite-agents-894031978246.us-central1.run.app"
)

SUPPORTED_EXTS = {".pdf", ".docx", ".txt", ".md"}
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
# gog CLI wrappers (module-level so tests can monkeypatch them)
# ---------------------------------------------------------------------------
def _gog_ls(folder_id: str) -> list[dict[str, Any]]:
    """List files in a Drive folder via gog. Raises RuntimeError on failure."""
    cmd = [
        GOG_BIN, "drive", "ls",
        "-a", DRIVE_ACCOUNT,
        "--parent", folder_id,
        "-j", "--max", "100", "--no-input",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as exc:
        raise RuntimeError(f"gog CLI not available: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("gog drive ls timed out") from exc
    if result.returncode != 0:
        raise RuntimeError(f"gog drive ls failed: {result.stderr.strip()[:300]}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gog drive ls returned unparseable output: {exc}") from exc
    return data.get("files", []) if isinstance(data, dict) else []


def _gog_download(file_id: str, out_path: str) -> None:
    """Download one Drive file via gog. Raises RuntimeError on failure."""
    cmd = [
        GOG_BIN, "drive", "download", file_id,
        "-a", DRIVE_ACCOUNT,
        "--out", out_path, "--no-input", "-y",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError as exc:
        raise RuntimeError(f"gog CLI not available: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("gog drive download timed out") from exc
    if result.returncode != 0:
        raise RuntimeError(f"download failed: {result.stderr.strip()[:300]}")
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError("download produced no file")


def list_folder_files(folder_id: str) -> list[dict[str, Any]]:
    """Recursively list files (bounded depth/count). Each entry:
    {file_id, filename, mime_type, size}."""
    out: list[dict[str, Any]] = []

    def _walk(fid: str, depth: int) -> None:
        if len(out) >= MAX_FILES:
            return
        for f in _gog_ls(fid):
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
    ext = os.path.splitext(filename)[1].lower()
    return ext in SUPPORTED_EXTS


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
            entry = {
                "file_id": f["file_id"],
                "filename": f["filename"],
                "mime_type": f["mime_type"],
                "size": f["size"],
                "doc_type": guess_doc_type(f["filename"]),
            }
            if not _is_supported(f["filename"], f["mime_type"]):
                entry["status"] = "skipped"
                entry["detail"] = f"unsupported type ({f['mime_type']})"
                docs.append(entry)
                continue

            local_path = os.path.join(tmpdir, f"{f['file_id']}_{os.path.basename(f['filename'])}")
            try:
                await asyncio.to_thread(_gog_download, f["file_id"], local_path)
            except RuntimeError as exc:
                entry["status"] = "failed"
                entry["detail"] = f"Drive download failed: {exc}"
                docs.append(entry)
                continue

            try:
                with open(local_path, "rb") as fh:
                    content = fh.read()
                await upload_to_datasite(site_id, f["filename"], content, entry["doc_type"])
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
