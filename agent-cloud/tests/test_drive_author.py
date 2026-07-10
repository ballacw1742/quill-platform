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
from unittest.mock import ANY, AsyncMock, MagicMock, patch

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


# ===========================================================================
# Phase H — per-project Drive subfolder tests
# ===========================================================================

# ---------------------------------------------------------------------------
# _sanitize_subfolder — pure unit tests (no google libs needed)
# ---------------------------------------------------------------------------

def test_sanitize_subfolder_strips_whitespace():
    from app.drive_author import _sanitize_subfolder
    assert _sanitize_subfolder("  My Project  ") == "My Project"


def test_sanitize_subfolder_removes_slashes():
    from app.drive_author import _sanitize_subfolder
    assert _sanitize_subfolder("path/to/folder") == "pathtofolder"
    assert _sanitize_subfolder("a\\b") == "ab"


def test_sanitize_subfolder_caps_length():
    from app.drive_author import _sanitize_subfolder
    long_name = "A" * 200
    result = _sanitize_subfolder(long_name)
    assert len(result) == 100


def test_sanitize_subfolder_empty_returns_none():
    from app.drive_author import _sanitize_subfolder
    assert _sanitize_subfolder("") is None
    assert _sanitize_subfolder("   ") is None
    assert _sanitize_subfolder("//\\\\") is None


def test_sanitize_subfolder_collapses_spaces():
    from app.drive_author import _sanitize_subfolder
    assert _sanitize_subfolder("A  B   C") == "A B C"


# ---------------------------------------------------------------------------
# _resolve_or_create_subfolder — mock drive_svc
# ---------------------------------------------------------------------------

def _make_drive_svc_with_existing(folder_id: str = "existing-sub-id", drive_id: str = "shared-drive-id"):
    """Return a mock drive service that finds an existing folder on list()."""
    svc = MagicMock()
    # files().get() returns the parent's driveId
    svc.files.return_value.get.return_value.execute.return_value = {"driveId": drive_id}
    # files().list() returns the existing folder
    svc.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": folder_id}]
    }
    return svc


def _make_drive_svc_no_existing(new_folder_id: str = "new-sub-id", drive_id: str = ""):
    """Return a mock drive service that finds nothing and creates a new folder."""
    svc = MagicMock()
    # files().get() returns the parent's driveId (empty = personal drive)
    svc.files.return_value.get.return_value.execute.return_value = {"driveId": drive_id}
    # files().list() returns nothing
    svc.files.return_value.list.return_value.execute.return_value = {"files": []}
    # files().create() returns the new folder
    svc.files.return_value.create.return_value.execute.return_value = {"id": new_folder_id}
    return svc


def test_resolve_or_create_subfolder_returns_existing_id():
    """When the subfolder already exists, return its id without creating."""
    from app.drive_author import _resolve_or_create_subfolder

    svc = _make_drive_svc_with_existing("existing-id-abc")
    result = _resolve_or_create_subfolder(svc, "parent-folder-id", "My Project")
    assert result == "existing-id-abc"
    # list was called; create was NOT called
    svc.files.return_value.create.assert_not_called()


def test_resolve_or_create_subfolder_creates_when_not_found():
    """When no existing subfolder, create one and return the new id."""
    from app.drive_author import _resolve_or_create_subfolder

    svc = _make_drive_svc_no_existing("brand-new-id")
    result = _resolve_or_create_subfolder(svc, "parent-folder-id", "My Project")
    assert result == "brand-new-id"
    # create WAS called
    svc.files.return_value.create.assert_called_once()
    call_kwargs = svc.files.return_value.create.call_args
    body = call_kwargs[1]["body"] if "body" in call_kwargs[1] else call_kwargs[0][0]
    assert body.get("name") == "My Project"
    assert body.get("mimeType") == "application/vnd.google-apps.folder"
    assert "parent-folder-id" in body.get("parents", [])


def test_resolve_or_create_subfolder_race_rerquery():
    """If create() raises (race condition), re-query and return the winner's id."""
    from app.drive_author import _resolve_or_create_subfolder

    svc = MagicMock()
    # get() returns the driveId
    svc.files.return_value.get.return_value.execute.return_value = {"driveId": ""}
    # list() returns nothing on first call, then returns the winner on re-query
    list_results = [{"files": []}, {"files": [{"id": "winner-id"}]}]
    call_count = [0]
    def _list_execute():
        r = list_results[min(call_count[0], len(list_results) - 1)]
        call_count[0] += 1
        return r
    svc.files.return_value.list.return_value.execute.side_effect = _list_execute
    # create() raises to simulate race
    svc.files.return_value.create.return_value.execute.side_effect = Exception("already exists")

    result = _resolve_or_create_subfolder(svc, "parent-id", "Raced Project")
    assert result == "winner-id"


def test_resolve_or_create_subfolder_shared_drive_uses_corpora():
    """When parent is in a Shared Drive, the list query uses corpora='drive'."""
    from app.drive_author import _resolve_or_create_subfolder

    svc = _make_drive_svc_with_existing("existing-id", drive_id="shared-drive-xyz")
    _resolve_or_create_subfolder(svc, "parent-id", "Project A")

    # Verify the list call included corpora + driveId
    call_kwargs = svc.files.return_value.list.call_args[1]
    assert call_kwargs.get("corpora") == "drive"
    assert call_kwargs.get("driveId") == "shared-drive-xyz"


def test_resolve_or_create_subfolder_personal_drive_no_corpora():
    """When parent is on a personal Drive (no driveId), no corpora is set."""
    from app.drive_author import _resolve_or_create_subfolder

    svc = _make_drive_svc_with_existing("existing-id", drive_id="")
    _resolve_or_create_subfolder(svc, "parent-id", "Project B")

    call_kwargs = svc.files.return_value.list.call_args[1]
    assert "corpora" not in call_kwargs
    assert "driveId" not in call_kwargs


# ---------------------------------------------------------------------------
# author_to_drive — subfolder param integration (mocked google libs)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_author_to_drive_with_subfolder_routes_into_subfolder():
    """When subfolder is set and DRIVE_FOLDER_ID is set, file is created in
    the resolved subfolder id, not the root folder id."""
    import app.drive_author as da

    fake_google, fake_oauth2, fake_gc, fake_disc, fake_creds = _make_fake_google_libs()

    sa_json = json.dumps({"type": "service_account", "project_id": "test"})
    mock_settings = _settings_with(
        DRIVE_ENABLED=True,
        DRIVE_SERVICE_ACCOUNT_JSON=sa_json,
        DRIVE_FOLDER_ID="root-folder-id",
    )

    # Patch _resolve_or_create_subfolder to return a known subfolder id.
    with patch.object(da, "_GOOGLE_AVAILABLE", True), \
         patch("app.drive_author.get_settings", return_value=mock_settings), \
         patch("app.drive_author._build_credentials", return_value=fake_creds), \
         patch("app.drive_author._build_drive_service", return_value=MagicMock()), \
         patch("app.drive_author._resolve_or_create_subfolder", return_value="sub-folder-id") as mock_resolve, \
         patch.dict(sys.modules, {
             "google": fake_google,
             "google.oauth2": fake_oauth2,
             "google.oauth2.service_account": fake_oauth2.service_account,
             "googleapiclient": fake_gc,
             "googleapiclient.discovery": fake_disc,
         }):
        block = await da.author_to_drive(
            "doc", "Project Report", "content here", subfolder="Acme Bridge"
        )

    # Subfolder resolver was called
    mock_resolve.assert_called_once_with(ANY, "root-folder-id", "Acme Bridge")
    # The returned block notes the subfolder
    assert block["subfolder"] == "Acme Bridge"
    assert block["mode"] == "drive"
    assert block["kind"] == "doc"


@pytest.mark.asyncio
async def test_author_to_drive_without_subfolder_unchanged():
    """When subfolder is None, behavior is byte-for-byte identical to Phase F
    (no _resolve_or_create_subfolder call, no 'subfolder' in block)."""
    import app.drive_author as da

    fake_google, fake_oauth2, fake_gc, fake_disc, fake_creds = _make_fake_google_libs()

    sa_json = json.dumps({"type": "service_account", "project_id": "test"})
    mock_settings = _settings_with(
        DRIVE_ENABLED=True,
        DRIVE_SERVICE_ACCOUNT_JSON=sa_json,
        DRIVE_FOLDER_ID="root-folder-id",
    )

    with patch.object(da, "_GOOGLE_AVAILABLE", True), \
         patch("app.drive_author.get_settings", return_value=mock_settings), \
         patch("app.drive_author._resolve_or_create_subfolder") as mock_resolve, \
         patch.dict(sys.modules, {
             "google": fake_google,
             "google.oauth2": fake_oauth2,
             "google.oauth2.service_account": fake_oauth2.service_account,
             "googleapiclient": fake_gc,
             "googleapiclient.discovery": fake_disc,
         }):
        block = await da.author_to_drive("doc", "Flat Doc", "content", subfolder=None)

    # No subfolder resolution
    mock_resolve.assert_not_called()
    # No subfolder key in block
    assert "subfolder" not in block
    assert block["mode"] == "drive"


@pytest.mark.asyncio
async def test_author_to_drive_subfolder_only_when_drive_folder_id_set():
    """When subfolder is provided but DRIVE_FOLDER_ID is empty, no subfolder resolution
    occurs (can't create subfolder with no root) — writes to flat root (empty folder_id)."""
    import app.drive_author as da

    fake_google, fake_oauth2, fake_gc, fake_disc, fake_creds = _make_fake_google_libs()

    sa_json = json.dumps({"type": "service_account", "project_id": "test"})
    mock_settings = _settings_with(
        DRIVE_ENABLED=True,
        DRIVE_SERVICE_ACCOUNT_JSON=sa_json,
        DRIVE_FOLDER_ID="",  # no root folder
    )

    with patch.object(da, "_GOOGLE_AVAILABLE", True), \
         patch("app.drive_author.get_settings", return_value=mock_settings), \
         patch("app.drive_author._resolve_or_create_subfolder") as mock_resolve, \
         patch.dict(sys.modules, {
             "google": fake_google,
             "google.oauth2": fake_oauth2,
             "google.oauth2.service_account": fake_oauth2.service_account,
             "googleapiclient": fake_gc,
             "googleapiclient.discovery": fake_disc,
         }):
        block = await da.author_to_drive(
            "doc", "No-Root Doc", "content", subfolder="Any Project"
        )

    # No subfolder resolution — no root folder to resolve under
    mock_resolve.assert_not_called()
    # No subfolder key (it was cleared to None)
    assert "subfolder" not in block


# ---------------------------------------------------------------------------
# TaskContext — project_id and project_name fields
# ---------------------------------------------------------------------------

def test_task_context_has_project_fields():
    """TaskContext must expose project_id and project_name (both optional)."""
    from app.adk.base import TaskContext

    ctx = TaskContext(tenant_id="t1", agent_id="a1")
    assert hasattr(ctx, "project_id")
    assert hasattr(ctx, "project_name")
    assert ctx.project_id is None
    assert ctx.project_name is None


def test_task_context_accepts_project_fields():
    """TaskContext can be constructed with project_id and project_name."""
    from app.adk.base import TaskContext

    ctx = TaskContext(
        tenant_id="t1",
        agent_id="a1",
        project_id="proj-abc",
        project_name="Acme Bridge",
    )
    assert ctx.project_id == "proj-abc"
    assert ctx.project_name == "Acme Bridge"


# ---------------------------------------------------------------------------
# runner._exec_tool — project context injection into generate_deliverable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exec_tool_injects_drive_subfolder_for_generate_deliverable():
    """runner._exec_tool merges _drive_subfolder into args for generate_deliverable
    when the context has project_name set."""
    from unittest.mock import AsyncMock
    from app.adk.runner import AdkAgentRunner
    from app.adk.base import TaskContext

    runner = AdkAgentRunner.__new__(AdkAgentRunner)

    captured_args: list[dict] = []

    async def _fake_handler(args):
        captured_args.append(dict(args))
        return '{"status": "generated", "deliverable": {"drive": {"mode": "local"}}}'

    ctx = TaskContext(tenant_id="t", agent_id="a", project_name="Bridge Proj")

    with patch("app.adk.runner.ADK_TOOL_REGISTRY", {
        "generate_deliverable": MagicMock(handler=_fake_handler)
    }):
        await runner._exec_tool(
            "generate_deliverable",
            {"kind": "doc", "title": "T", "content": "c"},
            ["generate_deliverable"],
            ctx,
        )

    assert len(captured_args) == 1
    assert captured_args[0]["_drive_subfolder"] == "Bridge Proj"


@pytest.mark.asyncio
async def test_exec_tool_no_injection_when_no_project():
    """runner._exec_tool does NOT inject _drive_subfolder when context has no project."""
    from app.adk.runner import AdkAgentRunner
    from app.adk.base import TaskContext

    runner = AdkAgentRunner.__new__(AdkAgentRunner)

    captured_args: list[dict] = []

    async def _fake_handler(args):
        captured_args.append(dict(args))
        return '{"status": "generated", "deliverable": {"drive": {"mode": "local"}}}'

    ctx = TaskContext(tenant_id="t", agent_id="a")  # no project_name/project_id

    with patch("app.adk.runner.ADK_TOOL_REGISTRY", {
        "generate_deliverable": MagicMock(handler=_fake_handler)
    }):
        await runner._exec_tool(
            "generate_deliverable",
            {"kind": "doc", "title": "T", "content": "c"},
            ["generate_deliverable"],
            ctx,
        )

    assert len(captured_args) == 1
    assert "_drive_subfolder" not in captured_args[0]


@pytest.mark.asyncio
async def test_exec_tool_no_injection_for_other_tools():
    """runner._exec_tool does NOT inject _drive_subfolder for non-deliverable tools."""
    from app.adk.runner import AdkAgentRunner
    from app.adk.base import TaskContext

    runner = AdkAgentRunner.__new__(AdkAgentRunner)

    captured_args: list[dict] = []

    async def _fake_handler(args):
        captured_args.append(dict(args))
        return '{"result": "ok"}'

    ctx = TaskContext(tenant_id="t", agent_id="a", project_name="Some Project")

    with patch("app.adk.runner.ADK_TOOL_REGISTRY", {
        "web_fetch": MagicMock(handler=_fake_handler)
    }):
        await runner._exec_tool(
            "web_fetch",
            {"url": "https://example.com"},
            ["web_fetch"],
            ctx,
        )

    assert len(captured_args) == 1
    assert "_drive_subfolder" not in captured_args[0]


# ---------------------------------------------------------------------------
# _generate_deliverable — reads _drive_subfolder from args
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_deliverable_passes_subfolder_to_author():
    """When _drive_subfolder is in args, _generate_deliverable passes it to
    _author_to_drive as the subfolder keyword arg."""
    mock_drive_block = {
        "mode": "drive",
        "kind": "doc",
        "doc_id": "sub-doc-id",
        "url": "https://docs.google.com/document/d/sub-doc-id/edit",
        "title": "Project Doc",
        "subfolder": "Acme Bridge",
    }

    with patch("app.adk.registry.get_settings", return_value=_settings_with(DRIVE_ENABLED=True)):
        with patch("app.adk.registry._author_to_drive", new=AsyncMock(return_value=mock_drive_block)) as mock_author:
            from app.adk.registry import _generate_deliverable

            await _generate_deliverable({
                "kind": "doc",
                "title": "Project Doc",
                "content": "Content.",
                "_drive_subfolder": "Acme Bridge",
            })

    mock_author.assert_called_once_with(
        "doc", "Project Doc", "Content.", subfolder="Acme Bridge"
    )


@pytest.mark.asyncio
async def test_generate_deliverable_no_subfolder_when_key_absent():
    """When _drive_subfolder is absent, _author_to_drive is called with subfolder=None."""
    mock_drive_block = {
        "mode": "drive",
        "kind": "doc",
        "doc_id": "flat-doc-id",
        "url": "https://docs.google.com/document/d/flat-doc-id/edit",
        "title": "Flat Doc",
    }

    with patch("app.adk.registry.get_settings", return_value=_settings_with(DRIVE_ENABLED=True)):
        with patch("app.adk.registry._author_to_drive", new=AsyncMock(return_value=mock_drive_block)) as mock_author:
            from app.adk.registry import _generate_deliverable

            await _generate_deliverable({
                "kind": "doc",
                "title": "Flat Doc",
                "content": "Content.",
                # no _drive_subfolder key
            })

    mock_author.assert_called_once_with(
        "doc", "Flat Doc", "Content.", subfolder=None
    )
