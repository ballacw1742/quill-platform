"""Google Drive / Docs / Sheets authoring for Quill deliverables (Phase F, H).

Called by app/adk/registry.py `_author_to_drive` when DRIVE_ENABLED=true.
The caller already wraps us in a try/except and falls back to a local record on
any exception — so we MUST raise on failure and NEVER fake success.

Import guard: the google libraries are optional (not installed in dev/test
unless the operator explicitly adds them). If they are absent every public
function raises ImportError, which the caller treats as a drive authoring
failure and degrades gracefully to the local path. This means the module is
always importable, even when the google libraries are missing.

Scopes required:
  - https://www.googleapis.com/auth/drive
  - https://www.googleapis.com/auth/documents
  - https://www.googleapis.com/auth/spreadsheets

Operator setup: see agent-cloud/DRIVE_SETUP.md.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import get_settings

log = logging.getLogger("agentcloud.drive_author")

# ---------------------------------------------------------------------------
# Lazy-import guard — keep the module importable even without google libs.
# ---------------------------------------------------------------------------
_GOOGLE_AVAILABLE: bool | None = None  # None = not yet probed


def _check_google_libs() -> None:
    """Raise ImportError if the google client libraries are not installed."""
    global _GOOGLE_AVAILABLE  # noqa: PLW0603
    if _GOOGLE_AVAILABLE is True:
        return
    if _GOOGLE_AVAILABLE is False:
        raise ImportError(
            "google-api-python-client and/or google-auth are not installed. "
            "Run: pip install google-api-python-client google-auth"
        )
    try:
        import google.auth  # noqa: F401  (presence check)
        import googleapiclient.discovery  # noqa: F401  (presence check)
        _GOOGLE_AVAILABLE = True
    except ImportError as exc:
        _GOOGLE_AVAILABLE = False
        raise ImportError(
            "google-api-python-client and/or google-auth are not installed. "
            "Run: pip install google-api-python-client google-auth"
        ) from exc


# ---------------------------------------------------------------------------
# Subfolder name sanitization
# ---------------------------------------------------------------------------

_SUBFOLDER_MAX_LEN = 100


def _sanitize_subfolder(name: str) -> str | None:
    """Sanitize a subfolder display name for safe use as a Drive folder name.

    Rules:
    - Strip leading/trailing whitespace.
    - Remove path separators (/ and \\) to prevent traversal.
    - Collapse repeated spaces to a single space.
    - Truncate to _SUBFOLDER_MAX_LEN characters.
    - Return None if the result is empty (callers treat None as "no subfolder").
    """
    if not name:
        return None
    cleaned = re.sub(r"[/\\]", "", name)  # strip slashes
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned[:_SUBFOLDER_MAX_LEN]
    return cleaned or None


# ---------------------------------------------------------------------------
# Credential builder
# ---------------------------------------------------------------------------

_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _build_credentials():
    """Build Google credentials from DRIVE_SERVICE_ACCOUNT_JSON.

    Raises ValueError if the config is empty or malformed.
    Raises ImportError if google-auth is not installed.
    """
    _check_google_libs()
    from google.oauth2 import service_account  # type: ignore[import]

    s = get_settings()
    sa_json_str = s.DRIVE_SERVICE_ACCOUNT_JSON.strip()
    if not sa_json_str:
        raise ValueError(
            "DRIVE_SERVICE_ACCOUNT_JSON is empty — configure a service account "
            "key before setting DRIVE_ENABLED=true. See DRIVE_SETUP.md."
        )
    try:
        sa_info = json.loads(sa_json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"DRIVE_SERVICE_ACCOUNT_JSON is not valid JSON: {exc}"
        ) from exc

    return service_account.Credentials.from_service_account_info(
        sa_info, scopes=_SCOPES
    )


# ---------------------------------------------------------------------------
# Shared Drive subfolder resolution
# ---------------------------------------------------------------------------


def _get_drive_id(drive_svc, parent_folder_id: str) -> str:
    """Return the Shared Drive ID that owns parent_folder_id.

    Needed for corpora='drive' queries which require an explicit driveId.
    Falls back to an empty string when the parent is on a personal Drive
    (no driveId field in the file metadata).
    """
    meta = drive_svc.files().get(
        fileId=parent_folder_id,
        fields="driveId",
        supportsAllDrives=True,
    ).execute()
    return meta.get("driveId", "")


def _resolve_or_create_subfolder(
    drive_svc, parent_folder_id: str, subfolder_name: str
) -> str:
    """Return the Drive folder id for ``<parent>/<subfolder_name>``.

    1. Queries for an existing non-trashed folder with the given name
       under ``parent_folder_id`` (Shared Drive-aware query).
    2. Returns its id if found.
    3. Creates a new folder if not found and returns the new id.
    4. If creation races (another caller created concurrently), re-queries
       once and returns the winner's id.

    Parameters
    ----------
    drive_svc:
        An authenticated ``googleapiclient`` Drive v3 service object.
    parent_folder_id:
        The Drive folder id of the root (parent) folder.
    subfolder_name:
        Display name for the subfolder (must already be sanitized/non-empty).

    Returns
    -------
    str
        The Drive folder id of the resolved (or freshly created) subfolder.
    """
    # Shared Drive-aware list query.
    drive_id = _get_drive_id(drive_svc, parent_folder_id)

    def _query_existing() -> str | None:
        q = (
            f"mimeType='application/vnd.google-apps.folder'"
            f" and name={json.dumps(subfolder_name)}"
            f" and '{parent_folder_id}' in parents"
            f" and trashed=false"
        )
        kwargs: dict[str, Any] = {
            "q": q,
            "fields": "files(id)",
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if drive_id:
            kwargs["corpora"] = "drive"
            kwargs["driveId"] = drive_id
        res = drive_svc.files().list(**kwargs).execute()
        files = res.get("files", [])
        return files[0]["id"] if files else None

    existing_id = _query_existing()
    if existing_id:
        return existing_id

    # Not found — create it.
    try:
        created = drive_svc.files().create(
            body={
                "name": subfolder_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_folder_id],
            },
            fields="id",
            supportsAllDrives=True,
        ).execute()
        return created["id"]
    except Exception:  # noqa: BLE001 — race: another caller created it first
        # Re-query once; if still not found, let the exception propagate.
        winner_id = _query_existing()
        if winner_id:
            return winner_id
        raise


# ---------------------------------------------------------------------------
# Doc authoring
# ---------------------------------------------------------------------------

def _build_docs_service(credentials):
    _check_google_libs()
    from googleapiclient.discovery import build  # type: ignore[import]
    return build("docs", "v1", credentials=credentials, cache_discovery=False)


def _build_drive_service(credentials):
    _check_google_libs()
    from googleapiclient.discovery import build  # type: ignore[import]
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _build_sheets_service(credentials):
    _check_google_libs()
    from googleapiclient.discovery import build  # type: ignore[import]
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _create_doc(title: str, content: str, folder_id: str) -> dict[str, Any]:
    """Create a Google Doc and insert plain-text content.

    Returns a partial drive_block: {doc_id, url}.
    Raises on any API error.
    """
    credentials = _build_credentials()
    docs_svc = _build_docs_service(credentials)
    drive_svc = _build_drive_service(credentials)

    # 1. Create an empty document.
    #    When a target folder is set, create the file DIRECTLY in that folder
    #    via the Drive API (parents=[folder_id]). This is required for
    #    service accounts on personal Google accounts, which have no writable
    #    "My Drive" root — calling docs.documents().create() there returns 403.
    #    Creating inside a user-shared folder (owned by a real user) succeeds.
    if folder_id:
        file_meta = drive_svc.files().create(
            body={
                "name": title,
                "mimeType": "application/vnd.google-apps.document",
                "parents": [folder_id],
            },
            fields="id",
            supportsAllDrives=True,
        ).execute()
        doc_id: str = file_meta["id"]
    else:
        doc = docs_svc.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]
    url: str = f"https://docs.google.com/document/d/{doc_id}/edit"

    # 2. Insert text content at the beginning of the document.
    #    We use a simple batchUpdate with a single insertText request.
    #    The body always starts with a single paragraph; index 1 is the
    #    insertion point right after the start-of-body structural element.
    if content:
        docs_svc.documents().batchUpdate(
            documentId=doc_id,
            body={
                "requests": [
                    {
                        "insertText": {
                            "location": {"index": 1},
                            "text": content,
                        }
                    }
                ]
            },
        ).execute()

    # (File was created directly in the target folder above when folder_id is
    # set; no move step needed. Without a folder_id the doc lives in the SA's
    # default location.)

    return {"doc_id": doc_id, "url": url}


def _create_sheet(title: str, rows: list[list[Any]], folder_id: str) -> dict[str, Any]:
    """Create a Google Sheet and write the rows.

    Returns a partial drive_block: {sheet_id, url}.
    Raises on any API error.
    """
    credentials = _build_credentials()
    sheets_svc = _build_sheets_service(credentials)
    drive_svc = _build_drive_service(credentials)

    # 1. Create an empty spreadsheet.
    #    As with docs: create directly in the target folder via the Drive API
    #    when folder_id is set, so service accounts on personal Google accounts
    #    (no writable My Drive root) can author into a user-shared folder.
    if folder_id:
        file_meta = drive_svc.files().create(
            body={
                "name": title,
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "parents": [folder_id],
            },
            fields="id",
            supportsAllDrives=True,
        ).execute()
        sheet_id: str = file_meta["id"]
    else:
        spreadsheet = (
            sheets_svc.spreadsheets()
            .create(body={"properties": {"title": title}})
            .execute()
        )
        sheet_id = spreadsheet["spreadsheetId"]
    url: str = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"

    # 2. Write rows if provided.
    if rows:
        # Normalize every cell to str so the Sheets API is happy.
        normalized = [
            [str(cell) for cell in row] for row in rows
        ]
        range_notation = "Sheet1"
        sheets_svc.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=range_notation,
            valueInputOption="RAW",
            body={"values": normalized},
        ).execute()

    # (Created directly in the target folder above when folder_id is set.)

    return {"sheet_id": sheet_id, "url": url}


# ---------------------------------------------------------------------------
# Public async entry-point (called by registry._author_to_drive)
# ---------------------------------------------------------------------------

async def author_to_drive(
    kind: str,
    title: str,
    content: Any,
    *,
    subfolder: str | None = None,
) -> dict[str, Any]:
    """Author a deliverable to Google Drive.

    Parameters
    ----------
    kind:
        'doc' or 'sheet'.
    title:
        Document / spreadsheet title (truncated to 255 chars).
    content:
        For 'doc': a str (plain text / markdown).
        For 'sheet': a list of rows (each row a list of cell values).
    subfolder:
        Optional display name for a per-project subfolder under the root
        DRIVE_FOLDER_ID.  When set AND DRIVE_FOLDER_ID is configured the file
        is created inside ``<root>/<subfolder>/`` rather than directly in the
        root.  The subfolder is created on first use (idempotent; safe for
        concurrent calls).  When None (default) behaviour is byte-for-byte
        identical to the previous flat-root behaviour.

    Returns
    -------
    drive_block dict:
        {
            "mode":    "drive",
            "kind":    "doc" | "sheet",
            "doc_id":  "<google-doc-id>",   # doc only
            "sheet_id":"<google-sheet-id>", # sheet only
            "url":     "https://docs.google.com/...",
            "title":   "<title>",
            "subfolder": "<name>",          # only when subfolder was used
        }

    Raises
    ------
    ImportError  — google libs not installed
    ValueError   — bad config (empty SA JSON, bad JSON, etc.)
    Exception    — any Google API error

    The caller in registry.py catches ALL exceptions and degrades to a local
    deliverable record, so we must NEVER swallow errors here.
    """
    s = get_settings()
    root_folder_id = (s.DRIVE_FOLDER_ID or "").strip()

    # Resolve effective folder: root → subfolder (when provided and root exists).
    safe_sub = _sanitize_subfolder(subfolder or "")
    if safe_sub and root_folder_id:
        _check_google_libs()  # ensure libs available before building service
        credentials = _build_credentials()
        drive_svc = _build_drive_service(credentials)
        folder_id = _resolve_or_create_subfolder(drive_svc, root_folder_id, safe_sub)
        log.info(
            "drive_author: resolved subfolder %r → folder_id=%s", safe_sub, folder_id
        )
    else:
        folder_id = root_folder_id
        safe_sub = None  # no subfolder used

    safe_title = str(title)[:255]

    log.info(
        "drive_author: creating %s %r (folder=%r subfolder=%r)",
        kind, safe_title, folder_id or "<root>", safe_sub,
    )

    if kind == "doc":
        if not isinstance(content, str):
            raise TypeError(f"doc content must be a str, got {type(content)!r}")
        partial = _create_doc(safe_title, content, folder_id)
        block: dict[str, Any] = {
            "mode": "drive",
            "kind": "doc",
            "doc_id": partial["doc_id"],
            "url": partial["url"],
            "title": safe_title,
        }
        if safe_sub:
            block["subfolder"] = safe_sub
        return block

    elif kind == "sheet":
        if not isinstance(content, list):
            raise TypeError(f"sheet content must be a list of rows, got {type(content)!r}")
        partial = _create_sheet(safe_title, content, folder_id)
        block = {
            "mode": "drive",
            "kind": "sheet",
            "sheet_id": partial["sheet_id"],
            "url": partial["url"],
            "title": safe_title,
        }
        if safe_sub:
            block["subfolder"] = safe_sub
        return block

    else:
        raise ValueError(f"unsupported kind {kind!r}; must be 'doc' or 'sheet'")
