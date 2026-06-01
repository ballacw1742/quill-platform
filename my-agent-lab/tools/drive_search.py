"""Google Drive search tool — wraps the gog CLI / Drive API for document lookup."""
from __future__ import annotations

from typing import Any

from google.adk.tools import FunctionTool


def search_drive(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Search Google Drive for documents matching a query string.

    TODO: wire to the gog CLI or Google Drive API v3.
      - Via gog CLI: run `gog drive search "<query>"` and parse JSON output.
      - Via API: use google-api-python-client with Drive v3 credentials.

    Currently returns fixture/stub data so testing doesn't crash.

    Args:
        query: Full-text search query (supports Drive query syntax,
            e.g. "fullText contains 'RFI-042' and mimeType='application/pdf'").
        max_results: Maximum number of results to return (default 10).

    Returns:
        List of dicts, each with:
            'file_id' (str) — Google Drive file ID.
            'name' (str) — file name.
            'mime_type' (str) — MIME type.
            'web_view_link' (str) — shareable URL.
            'modified_time' (str) — ISO datetime of last modification.
            'snippet' (str | None) — text snippet matching the query.
    """
    # TODO: implement real search. Example:
    #   import subprocess, json
    #   result = subprocess.run(
    #       ["gog", "drive", "search", query, "--limit", str(max_results), "--json"],
    #       capture_output=True, text=True, check=True,
    #   )
    #   return json.loads(result.stdout)

    return [
        {
            "file_id": "STUB_FILE_ID",
            "name": "[STUB] search_drive result",
            "mime_type": "application/pdf",
            "web_view_link": "https://drive.google.com/STUB",
            "modified_time": "1970-01-01T00:00:00Z",
            "snippet": (
                f"[STUB] search_drive called with query={query!r}. "
                "TODO: implement real Drive search."
            ),
        }
    ]


search_drive_tool = FunctionTool(func=search_drive)
