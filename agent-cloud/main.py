"""Uvicorn entrypoint shim — the platform core lives in app/ (A1).

Kept so the spike deploy command (`uvicorn main:app`) keeps working.
"""

from app.api import app  # noqa: F401
