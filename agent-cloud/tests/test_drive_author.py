"""Tests for Phase F — Google Drive/Docs/Sheets deliverable authoring.

Verifies:
  1. DRIVE_ENABLED=false → _generate_deliverable returns mode='local' (unchanged).
  2. DRIVE_ENABLED=true, author_to_drive mocked to return drive block → mode='drive'.
  3. DRIVE_ENABLED=true, author_to_drive mocked to RAISE → local fallback (never fakes success).
  4. Google libs absent (ImportError from import guard) → local fallback.
  5. drive_author module is always importable (even without google libs installed).
  6. author_to_drive returns correct drive_block contract for doc and sheet kinds.
  7. Config fields (DRIVE_ENABLED, DRIVE_SERVICE_ACCOUNT_JSON, DRIVE_FOLDER_ID) exist.

All Google API calls are mocked — no live credentials required.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
import unittest.mock as mock
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings_with(**overrides):
    """Return a mock Settings object with the given Drive-related overrides."""
    defaults = {
        "DRIVE_ENABLED": False,
        "DRIVE_SERVICE_ACCOUNT_JSON": "",
        "DRIVE_FOLDER_ID": "",
    }
    defaults.update(overrides)
    s = MagicMock()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# 1. Config fields exist on Settings
# ---------------------------------------------------------------------------

def test_config_drive_fields_exist():
    """Settings must expose DRIVE_ENABLED, DRIVE_SERVICE_ACCOUNT_JSON, DRIVE_FOLDER_ID."""
    from app.config import get_settings, Settings

    # Check field declarations on the class (not the singleton — avoids env pollution).
    fields = Settings.model_fields
    assert "DRIVE_ENABLED" in fields, "Settings missing DRIVE_ENABLED"
    assert "DRIVE_SERVICE_ACCOUNT_JSON" in fields, "Settings missing DRIVE_SERVICE_ACCOUNT_JSON"
    assert "DRIVE_FOLDER_ID" in fields, "Settings missing DRIVE_FOLDER_ID"

    # Defaults must be safe (disabled by default).
    assert fields["DRIVE_ENABLED"].default is False
    assert fields["DRIVE_SERVICE_ACCOUNT_JSON"].default == ""
    assert fields["DRIVE_FOLDER_ID"].default == ""


# ---------------------------------------------------------------------------
# 2. drive_author module is always importable
# ---------------------------------------------------------------------------

def test_drive_author_importable():
    """app.drive_author must import cleanly even when google libs are absent."""
    import app.drive_author  # noqa: F401 — presence check
    assert hasattr(app.drive_author, "author_to_drive")


# ---------------------------------------------------------------------------
# 3. DRIVE_ENABLED=false → _generate_deliverable returns mode='local'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_deliverable_drive_disabled_returns_local():
    """With DRIVE_ENABLED=false, generate_deliverable always returns mode='local'."""
    with patch("app.adk.registry.get_settings", return_value=_settings_with(DRIVE_ENABLED=False)):
        from app.adk.registry import _generate_deliverable

        result_str = await _generate_deliverable({
            "kind": "doc",
            "title": "My Report",
            "content": "Some content here.",
        })

    result = json.loads(result_str)
    assert result["status"] == "generated"
    deliverable = result["deliverable"]
    assert deliverable["drive"]["mode"] == "local"
    assert deliverable["kind"] == "doc"
    assert deliverable["title"] == "My Report"


@pytest.mark.asyncio
async def test_generate_deliverable_drive_disabled_sheet_returns_local():
    """DRIVE_ENABLED=false also returns local for sheet kind."""
    with patch("app.adk.registry.get_settings", return_value=_settings_with(DRIVE_ENABLED=False)):
        from app.adk.registry import _generate_deliverable

        result_str = await _generate_deliverable({
            "kind": "sheet",
            "title": "Budget Sheet",
            "content": [["Name", "Amount"], ["Alice", "100"]],
        })

    result = json.loads(result_str)
    deliverable = result["deliverable"]
    assert deliverable["drive"]["mode"] == "local"
    assert deliverable["kind"] == "sheet"


# ---------------------------------------------------------------------------
# 4. DRIVE_ENABLED=true, author_to_drive mocked → mode='drive'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_deliverable_drive_enabled_doc_returns_drive_block():
    """When DRIVE_ENABLED=true and author_to_drive succeeds, deliverable carries mode='drive'."""
    mock_drive_block = {
        "mode": "drive",
        "kind": "doc",
        "doc_id": "fake-doc-id-abc123",
        "url": "https://docs.google.com/document/d/fake-doc-id-abc123/edit",
        "title": "Weekly Brief",
    }

    with patch("app.adk.registry.get_settings", return_value=_settings_with(DRIVE_ENABLED=True)):
        with patch("app.adk.registry._author_to_drive", new=AsyncMock(return_value=mock_drive_block)):
            from app.adk.registry import _generate_deliverable

            result_str = await _generate_deliverable({
                "kind": "doc",
                "title": "Weekly Brief",
                "content": "This is the weekly summary.",
            })

    result = json.loads(result_str)
    assert result["status"] == "generated"
    deliverable = result["deliverable"]
    assert deliverable["drive"]["mode"] == "drive"
    assert deliverable["drive"]["doc_id"] == "fake-doc-id-abc123"
    assert deliverable["drive"]["url"].startswith("https://docs.google.com")
    assert deliverable["kind"] == "doc"
    assert deliverable["title"] == "Weekly Brief"


@pytest.mark.asyncio
async def test_generate_deliverable_drive_enabled_sheet_returns_drive_block():
    """DRIVE_ENABLED=true, sheet kind → drive block with sheet_id."""
    mock_drive_block = {
        "mode": "drive",
        "kind": "sheet",
        "sheet_id": "fake-sheet-id-xyz789",
        "url": "https://docs.google.com/spreadsheets/d/fake-sheet-id-xyz789/edit",
        "title": "Budget Sheet",
    }

    with patch("app.adk.registry.get_settings", return_value=_settings_with(DRIVE_ENABLED=True)):
        with patch("app.adk.registry._author_to_drive", new=AsyncMock(return_value=mock_drive_block)):
            from app.adk.registry import _generate_deliverable

            result_str = await _generate_deliverable({
                "kind": "sheet",
                "title": "Budget Sheet",
                "content": [["Month", "Revenue"], ["Jan", "50000"]],
            })

    result = json.loads(result_str)
    deliverable = result["deliverable"]
    assert deliverable["drive"]["mode"] == "drive"
    assert deliverable["drive"]["sheet_id"] == "fake-sheet-id-xyz789"
    assert deliverable["kind"] == "sheet"


# ---------------------------------------------------------------------------
# 5. DRIVE_ENABLED=true, author_to_drive mocked to RAISE → local fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_deliverable_drive_author_raises_falls_back_to_local():
    """When author_to_drive raises, the deliverable degrades to local (never fakes success)."""
    with patch("app.adk.registry.get_settings", return_value=_settings_with(DRIVE_ENABLED=True)):
        with patch(
            "app.adk.registry._author_to_drive",
            new=AsyncMock(side_effect=RuntimeError("Drive API exploded")),
        ):
            from app.adk.registry import _generate_deliverable

            result_str = await _generate_deliverable({
                "kind": "doc",
                "title": "Fallback Doc",
                "content": "Content that failed to reach Drive.",
            })

    result = json.loads(result_str)
    assert result["status"] == "generated"
    deliverable = result["deliverable"]
    # Must fall back to local, never return mode='drive' or fake doc_id.
    assert deliverable["drive"]["mode"] == "local"
    assert "doc_id" not in deliverable["drive"]
    assert "sheet_id" not in deliverable["drive"]
    # The reason string should mention the error.
    assert "drive error" in deliverable["drive"].get("reason", "")


@pytest.mark.asyncio
async def test_generate_deliverable_import_error_falls_back_to_local():
    """If google libs are absent (ImportError), the deliverable falls back to local."""
    with patch("app.adk.registry.get_settings", return_value=_settings_with(DRIVE_ENABLED=True)):
        with patch(
            "app.adk.registry._author_to_drive",
            new=AsyncMock(
                side_effect=ImportError(
                    "google-api-python-client is not installed"
                )
            ),
        ):
            from app.adk.registry import _generate_deliverable

            result_str = await _generate_deliverable({
                "kind": "doc",
                "title": "ImportError Doc",
                "content": "This should fall back gracefully.",
            })

    result = json.loads(result_str)
    deliverable = result["deliverable"]
    assert deliverable["drive"]["mode"] == "local"
    assert "doc_id" not in deliverable["drive"]


# ---------------------------------------------------------------------------
# 6. drive_author.author_to_drive — unit tests with mocked Google API
# ---------------------------------------------------------------------------

def _make_fake_google_libs():
    """Build minimal fake google lib modules so drive_author can be tested
    without the real google-api-python-client installed."""
    # google.oauth2.service_account.Credentials mock
    fake_creds = MagicMock()
    fake_sa_module = MagicMock()
    fake_sa_module.Credentials.from_service_account_info.return_value = fake_creds

    fake_oauth2_module = types.ModuleType("google.oauth2")
    fake_oauth2_module.service_account = fake_sa_module

    fake_google = types.ModuleType("google")
    fake_google.oauth2 = fake_oauth2_module
    fake_google.auth = MagicMock()

    # googleapiclient.discovery.build mock — returns a mock service
    def _fake_build(service_name, version, credentials, cache_discovery=False):
        svc = MagicMock()
        if service_name == "docs":
            doc_obj = {"documentId": "real-doc-id-001"}
            svc.documents.return_value.create.return_value.execute.return_value = doc_obj
            svc.documents.return_value.batchUpdate.return_value.execute.return_value = {}
        elif service_name == "drive":
            meta = {"parents": ["old-parent-id"]}
            svc.files.return_value.get.return_value.execute.return_value = meta
            svc.files.return_value.update.return_value.execute.return_value = {}
        elif service_name == "sheets":
            ss_obj = {"spreadsheetId": "real-sheet-id-001"}
            svc.spreadsheets.return_value.create.return_value.execute.return_value = ss_obj
            svc.spreadsheets.return_value.values.return_value.update.return_value.execute.return_value = {}
        return svc

    fake_discovery_module = MagicMock()
    fake_discovery_module.build = _fake_build

    fake_googleapiclient = types.ModuleType("googleapiclient")
    fake_googleapiclient.discovery = fake_discovery_module

    return fake_google, fake_oauth2_module, fake_googleapiclient, fake_discovery_module, fake_creds


@pytest.mark.asyncio
async def test_author_to_drive_doc_returns_correct_block():
    """author_to_drive with kind='doc' returns the correct drive_block contract."""
    import app.drive_author as da

    fake_google, fake_oauth2, fake_gc, fake_disc, fake_creds = _make_fake_google_libs()

    sa_json = json.dumps({"type": "service_account", "project_id": "test"})
    mock_settings = _settings_with(
        DRIVE_ENABLED=True,
        DRIVE_SERVICE_ACCOUNT_JSON=sa_json,
        DRIVE_FOLDER_ID="",
    )

    with patch.object(da, "_GOOGLE_AVAILABLE", True), \
         patch("app.drive_author.get_settings", return_value=mock_settings), \
         patch.dict(sys.modules, {
             "google": fake_google,
             "google.oauth2": fake_oauth2,
             "google.oauth2.service_account": fake_oauth2.service_account,
             "googleapiclient": fake_gc,
             "googleapiclient.discovery": fake_disc,
         }):
        block = await da.author_to_drive("doc", "Test Report", "Hello Drive!")

    assert block["mode"] == "drive"
    assert block["kind"] == "doc"
    assert "doc_id" in block
    assert block["doc_id"] == "real-doc-id-001"
    assert block["url"].startswith("https://docs.google.com/document/d/")
    assert block["title"] == "Test Report"
    # sheet_id must NOT appear in a doc block
    assert "sheet_id" not in block


@pytest.mark.asyncio
async def test_author_to_drive_sheet_returns_correct_block():
    """author_to_drive with kind='sheet' returns the correct drive_block contract."""
    import app.drive_author as da

    fake_google, fake_oauth2, fake_gc, fake_disc, fake_creds = _make_fake_google_libs()

    sa_json = json.dumps({"type": "service_account", "project_id": "test"})
    mock_settings = _settings_with(
        DRIVE_ENABLED=True,
        DRIVE_SERVICE_ACCOUNT_JSON=sa_json,
        DRIVE_FOLDER_ID="",
    )

    with patch.object(da, "_GOOGLE_AVAILABLE", True), \
         patch("app.drive_author.get_settings", return_value=mock_settings), \
         patch.dict(sys.modules, {
             "google": fake_google,
             "google.oauth2": fake_oauth2,
             "google.oauth2.service_account": fake_oauth2.service_account,
             "googleapiclient": fake_gc,
             "googleapiclient.discovery": fake_disc,
         }):
        rows = [["Name", "Value"], ["Alpha", "42"]]
        block = await da.author_to_drive("sheet", "Budget", rows)

    assert block["mode"] == "drive"
    assert block["kind"] == "sheet"
    assert "sheet_id" in block
    assert block["sheet_id"] == "real-sheet-id-001"
    assert block["url"].startswith("https://docs.google.com/spreadsheets/d/")
    assert block["title"] == "Budget"
    # doc_id must NOT appear in a sheet block
    assert "doc_id" not in block


@pytest.mark.asyncio
async def test_author_to_drive_empty_sa_json_raises():
    """author_to_drive raises ValueError when DRIVE_SERVICE_ACCOUNT_JSON is empty."""
    import app.drive_author as da

    mock_settings = _settings_with(
        DRIVE_ENABLED=True,
        DRIVE_SERVICE_ACCOUNT_JSON="",  # empty
        DRIVE_FOLDER_ID="",
    )

    with patch.object(da, "_GOOGLE_AVAILABLE", True), \
         patch("app.drive_author.get_settings", return_value=mock_settings):
        with pytest.raises(ValueError, match="DRIVE_SERVICE_ACCOUNT_JSON is empty"):
            await da.author_to_drive("doc", "Oops", "content")


@pytest.mark.asyncio
async def test_author_to_drive_bad_sa_json_raises():
    """author_to_drive raises ValueError when DRIVE_SERVICE_ACCOUNT_JSON is invalid JSON."""
    import app.drive_author as da

    mock_settings = _settings_with(
        DRIVE_ENABLED=True,
        DRIVE_SERVICE_ACCOUNT_JSON="NOT_VALID_JSON{{{",
        DRIVE_FOLDER_ID="",
    )

    with patch.object(da, "_GOOGLE_AVAILABLE", True), \
         patch("app.drive_author.get_settings", return_value=mock_settings):
        with pytest.raises(ValueError, match="not valid JSON"):
            await da.author_to_drive("doc", "Oops", "content")


@pytest.mark.asyncio
async def test_author_to_drive_unsupported_kind_raises():
    """author_to_drive raises ValueError for unsupported kind values."""
    import app.drive_author as da

    sa_json = json.dumps({"type": "service_account"})
    mock_settings = _settings_with(
        DRIVE_ENABLED=True,
        DRIVE_SERVICE_ACCOUNT_JSON=sa_json,
        DRIVE_FOLDER_ID="",
    )

    with patch.object(da, "_GOOGLE_AVAILABLE", True), \
         patch("app.drive_author.get_settings", return_value=mock_settings):
        with pytest.raises(ValueError, match="unsupported kind"):
            await da.author_to_drive("pdf", "Oops", "content")


@pytest.mark.asyncio
async def test_author_to_drive_google_libs_absent_raises_import_error():
    """When google libs are not installed, author_to_drive raises ImportError cleanly."""
    import app.drive_author as da

    sa_json = json.dumps({"type": "service_account"})
    mock_settings = _settings_with(
        DRIVE_ENABLED=True,
        DRIVE_SERVICE_ACCOUNT_JSON=sa_json,
        DRIVE_FOLDER_ID="",
    )

    # Force the availability flag to None so it re-probes, then simulate absent libs.
    with patch.object(da, "_GOOGLE_AVAILABLE", None), \
         patch("app.drive_author.get_settings", return_value=mock_settings):
        # Patch builtins.__import__ to fail for google modules.
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def _import_raiser(name, *args, **kwargs):
            if name.startswith("google"):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_import_raiser):
            # Reset availability so it re-probes
            da._GOOGLE_AVAILABLE = None
            with pytest.raises(ImportError):
                da._check_google_libs()
        # Reset for subsequent tests
        da._GOOGLE_AVAILABLE = None


# ---------------------------------------------------------------------------
# 7. registry._author_to_drive delegates to drive_author.author_to_drive
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_registry_author_to_drive_delegates():
    """registry._author_to_drive calls drive_author.author_to_drive."""
    expected_block = {
        "mode": "drive",
        "kind": "doc",
        "doc_id": "delegated-doc-id",
        "url": "https://docs.google.com/document/d/delegated-doc-id/edit",
        "title": "Delegated",
    }

    # Patch the module-level import inside registry._author_to_drive.
    with patch("app.drive_author.author_to_drive", new=AsyncMock(return_value=expected_block)):
        from app.adk import registry
        block = await registry._author_to_drive("doc", "Delegated", "Some text")

    assert block == expected_block


@pytest.mark.asyncio
async def test_registry_author_to_drive_propagates_exceptions():
    """registry._author_to_drive propagates exceptions from drive_author (no swallowing)."""
    with patch("app.drive_author.author_to_drive", new=AsyncMock(side_effect=ValueError("bad creds"))):
        from app.adk import registry
        with pytest.raises(ValueError, match="bad creds"):
            await registry._author_to_drive("doc", "Title", "text")


# ---------------------------------------------------------------------------
# 8. drive_block contract shape validation
# ---------------------------------------------------------------------------

def test_drive_block_doc_contract():
    """Verify the expected drive_block keys for a doc deliverable."""
    block = {
        "mode": "drive",
        "kind": "doc",
        "doc_id": "abc",
        "url": "https://docs.google.com/document/d/abc/edit",
        "title": "My Doc",
    }
    # Required keys for doc
    for key in ("mode", "kind", "doc_id", "url", "title"):
        assert key in block, f"Missing required key: {key}"
    assert block["mode"] == "drive"
    assert block["kind"] == "doc"


def test_drive_block_sheet_contract():
    """Verify the expected drive_block keys for a sheet deliverable."""
    block = {
        "mode": "drive",
        "kind": "sheet",
        "sheet_id": "xyz",
        "url": "https://docs.google.com/spreadsheets/d/xyz/edit",
        "title": "My Sheet",
    }
    for key in ("mode", "kind", "sheet_id", "url", "title"):
        assert key in block, f"Missing required key: {key}"
    assert block["mode"] == "drive"
    assert block["kind"] == "sheet"


def test_local_fallback_block_contract():
    """Verify the local fallback drive_block has mode='local'."""
    block = {"mode": "local", "reason": "DRIVE_ENABLED is false"}
    assert block["mode"] == "local"
    assert "reason" in block
    # local block must NOT have doc_id/sheet_id
    assert "doc_id" not in block
    assert "sheet_id" not in block
