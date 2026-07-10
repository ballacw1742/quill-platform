"""Google Drive / Docs / Sheets authoring for Quill deliverables (Phase F).

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
    doc = docs_svc.documents().create(body={"title": title}).execute()
    doc_id: str = doc["documentId"]
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

    # 3. Optionally move the file to the target folder.
    if folder_id:
        # Retrieve the current parent(s) so we can remove them.
        meta = drive_svc.files().get(
            fileId=doc_id, fields="parents"
        ).execute()
        previous_parents = ",".join(meta.get("parents", []))
        drive_svc.files().update(
            fileId=doc_id,
            addParents=folder_id,
            removeParents=previous_parents,
            fields="id, parents",
        ).execute()

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
    spreadsheet = (
        sheets_svc.spreadsheets()
        .create(body={"properties": {"title": title}})
        .execute()
    )
    sheet_id: str = spreadsheet["spreadsheetId"]
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

    # 3. Optionally move the file to the target folder.
    if folder_id:
        meta = drive_svc.files().get(
            fileId=sheet_id, fields="parents"
        ).execute()
        previous_parents = ",".join(meta.get("parents", []))
        drive_svc.files().update(
            fileId=sheet_id,
            addParents=folder_id,
            removeParents=previous_parents,
            fields="id, parents",
        ).execute()

    return {"sheet_id": sheet_id, "url": url}


# ---------------------------------------------------------------------------
# Public async entry-point (called by registry._author_to_drive)
# ---------------------------------------------------------------------------

async def author_to_drive(kind: str, title: str, content: Any) -> dict[str, Any]:
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
    folder_id = (s.DRIVE_FOLDER_ID or "").strip()
    safe_title = str(title)[:255]

    log.info("drive_author: creating %s %r (folder=%r)", kind, safe_title, folder_id or "<root>")

    if kind == "doc":
        if not isinstance(content, str):
            raise TypeError(f"doc content must be a str, got {type(content)!r}")
        partial = _create_doc(safe_title, content, folder_id)
        return {
            "mode": "drive",
            "kind": "doc",
            "doc_id": partial["doc_id"],
            "url": partial["url"],
            "title": safe_title,
        }

    elif kind == "sheet":
        if not isinstance(content, list):
            raise TypeError(f"sheet content must be a list of rows, got {type(content)!r}")
        partial = _create_sheet(safe_title, content, folder_id)
        return {
            "mode": "drive",
            "kind": "sheet",
            "sheet_id": partial["sheet_id"],
            "url": partial["url"],
            "title": safe_title,
        }

    else:
        raise ValueError(f"unsupported kind {kind!r}; must be 'doc' or 'sheet'")
