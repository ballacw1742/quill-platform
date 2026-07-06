"""Shared Quill backend HTTP helper for specialist ADK agents.

Sprint 5.2 — the six specialist agents (facility_ops, sales, customer_success,
finance, intelligence, compliance) read live data from the Quill FastAPI
backend. They all go through this thin wrapper so the base URL, timeout, and
error handling live in one place.

Base URL resolution (first match wins):
  1. QUILL_API_BASE_URL   — explicit override for the specialist agents
  2. INTERNAL_API_URL      — same var the API service reads
  3. http://localhost:8080 — local dev default

Every helper returns plain Python data (never raises) so the LLM always gets a
usable value. On error it returns a dict with an ``error`` key describing what
went wrong; callers surface that to the user rather than fabricating data.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

_DEFAULT_BASE = "http://localhost:8080"


def _base_url() -> str:
    return (
        os.environ.get("QUILL_API_BASE_URL")
        or os.environ.get("INTERNAL_API_URL")
        or _DEFAULT_BASE
    ).rstrip("/")


def quill_get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET a Quill API path (e.g. ``/v1/campuses``) and return decoded JSON.

    Returns the decoded JSON on success. On any failure returns
    ``{"error": "<description>", "path": path}`` — never raises.

    Args:
        path: API path beginning with ``/`` (e.g. ``/v1/deals``).
        params: Optional query-string parameters.
    """
    url = f"{_base_url()}{path}"
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, params=params or {})
            if resp.status_code >= 400:
                return {
                    "error": f"API returned {resp.status_code}",
                    "detail": resp.text[:500],
                    "path": path,
                }
            return resp.json()
    except httpx.ConnectError as exc:
        return {"error": f"Quill API unreachable at {url}", "detail": str(exc), "path": path}
    except httpx.TimeoutException as exc:
        return {"error": "Quill API timed out", "detail": str(exc), "path": path}
    except Exception as exc:  # noqa: BLE001 — helpers must never raise into the LLM
        return {"error": "Unexpected error calling Quill API", "detail": str(exc), "path": path}


def as_items(payload: Any) -> list[dict]:
    """Normalize a list response to a plain list of dicts.

    Quill list endpoints use the ``{items, total, limit, offset}`` envelope
    (per CONTRIBUTING_AGENTS.md §1). This unwraps ``items`` when present and
    otherwise returns the payload if it is already a list. Anything else → [].
    """
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return [i for i in items if isinstance(i, dict)]
        return []
    if isinstance(payload, list):
        return [i for i in payload if isinstance(i, dict)]
    return []
