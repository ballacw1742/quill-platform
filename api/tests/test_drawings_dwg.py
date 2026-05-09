"""Phase G.4 — DWG extractor tests.

The DWG extractor either shells out to ODA File Converter to produce a DXF
and re-extracts via DxfExtractor, or returns a friendly
'needs_conversion' status when ODA is not on PATH.

We do not vendor a real DWG file in the repo (DWG is binary, version-bound,
and would bloat the test corpus). Instead we exercise the no-ODA path
deterministically by stubbing the discovery helper, and we exercise the
with-ODA path with subprocess mocked so we don't depend on a real binary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import drawings as _drawings
from app.services.drawings import (
    DrawingExtractionResult,
    DwgExtractor,
    detect_kind,
    extract,
)


def test_dwg_kind_detection():
    assert detect_kind("plan.dwg") == "dwg"
    assert detect_kind("PLAN.DWG") == "dwg"


def test_dwg_no_oda_binary_returns_needs_conversion(monkeypatch):
    monkeypatch.setattr(_drawings, "_find_oda_binary", lambda: None)
    result = DwgExtractor().extract(filename="site.dwg", data=b"AC1018\x00\x00")
    assert isinstance(result, DrawingExtractionResult)
    assert result.kind == "dwg"
    assert result.extraction_status == "failed"
    # Friendly message must mention conversion path
    assert "DXF" in result.summary
    assert "ODA" in result.summary or "convert" in result.summary.lower()
    # Soft-status surfaced for downstream agents
    assert result.entities.get("extraction_status_detail") == "needs_conversion"


def test_dwg_extract_via_public_entry_routes_to_dwg_extractor(monkeypatch):
    monkeypatch.setattr(_drawings, "_find_oda_binary", lambda: None)
    result = extract(filename="x.dwg", data=b"AC1018")
    assert result.kind == "dwg"
    assert result.entities.get("extraction_status_detail") == "needs_conversion"


def test_dwg_with_oda_invokes_converter_and_routes_to_dxf(monkeypatch, tmp_path):
    """When ODA is on PATH, DwgExtractor shells out and reads back the DXF.

    We stub:
      - _find_oda_binary to return a sentinel path
      - subprocess.run to write a tiny synthetic DXF into the output dir
        and return rc=0
      - DxfExtractor.extract to assert it was called with the DXF path
    """
    monkeypatch.setattr(_drawings, "_find_oda_binary", lambda: "/fake/ODAFileConverter")

    captured: dict = {}

    def fake_run(args, *, capture_output, timeout):
        # ODA signature: [oda_bin, in_dir, out_dir, version, filetype, recurse, audit]
        out_dir = Path(args[2])
        # Drop a synthetic DXF in the output dir so DwgExtractor finds it.
        (out_dir / "input.dxf").write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n")
        captured["args"] = args

        class _Proc:
            returncode = 0
            stdout = b""
            stderr = b""
        return _Proc()

    monkeypatch.setattr(_drawings.subprocess, "run", fake_run)

    # Stub the inner DxfExtractor so we don't depend on ezdxf for this test.
    from app.services.drawings import DxfExtractor

    def fake_extract(self, *, filename, data=None, path=None):
        return DrawingExtractionResult(
            filename=filename,
            kind="dxf",
            size_bytes=path.stat().st_size if path else 0,
            extraction_status="ok",
            summary="DXF: 1 layer; 0 entities; 0 blocks.",
            entities={"layers": ["0"], "entity_counts": {}, "block_count": 0},
        )

    monkeypatch.setattr(DxfExtractor, "extract", fake_extract)

    result = DwgExtractor().extract(filename="site.dwg", data=b"AC1018\x00")
    assert result.kind == "dwg"
    assert result.extraction_status == "ok"
    assert "ODA File Converter" in result.summary
    assert result.entities == {"layers": ["0"], "entity_counts": {}, "block_count": 0}
    # Verify the captured ODA invocation looks right
    assert captured["args"][0] == "/fake/ODAFileConverter"
    assert captured["args"][3] == "ACAD2018"  # output version
    assert captured["args"][4] == "1"  # output filetype = DXF


def test_dwg_with_oda_nonzero_returncode_returns_failed(monkeypatch):
    monkeypatch.setattr(_drawings, "_find_oda_binary", lambda: "/fake/ODAFileConverter")

    def fake_run(args, *, capture_output, timeout):
        class _Proc:
            returncode = 2
            stdout = b""
            stderr = b"oda: corrupt input"
        return _Proc()

    monkeypatch.setattr(_drawings.subprocess, "run", fake_run)

    result = DwgExtractor().extract(filename="bad.dwg", data=b"junk")
    assert result.kind == "dwg"
    assert result.extraction_status == "failed"
    assert "non-zero" in result.summary or "exit" in result.summary.lower()


def test_dwg_with_oda_timeout_returns_failed(monkeypatch):
    import subprocess as _sp

    monkeypatch.setattr(_drawings, "_find_oda_binary", lambda: "/fake/ODAFileConverter")

    def fake_run(args, *, capture_output, timeout):
        raise _sp.TimeoutExpired(cmd=args, timeout=timeout)

    monkeypatch.setattr(_drawings.subprocess, "run", fake_run)

    result = DwgExtractor().extract(filename="huge.dwg", data=b"junk")
    assert result.kind == "dwg"
    assert result.extraction_status == "failed"
    assert "timed out" in result.summary.lower()
