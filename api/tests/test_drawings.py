"""Drawing extraction service tests \u2014 Phase G.1.

Each test builds the smallest valid file of its format in-memory and runs
it through the extractor. We do not vendor real-world public-domain
drawings into the repo; the synthetic fixtures keep these tests
hermetic and fast.

If a heavy dependency (ifcopenshell, ezdxf, pdfplumber, pypdfium2) is
not installed, the relevant test is skipped \u2014 the extractor still
returns a structured `DrawingExtractionResult` (with extraction_status
'failed' or 'partial') in that case, which the tests verify separately.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from app.services.drawings import (
    DrawingExtractionResult,
    DwgExtractor,
    RvtExtractor,
    detect_kind,
    extract,
)


# ---------------------------------------------------------------------------
# Kind detection
# ---------------------------------------------------------------------------
def test_detect_kind_recognizes_supported_formats():
    assert detect_kind("foo.pdf") == "pdf"
    assert detect_kind("FOO.PDF") == "pdf"
    assert detect_kind("model.ifc") == "ifc"
    assert detect_kind("site.dxf") == "dxf"
    assert detect_kind("plan.dwg") == "dwg"
    assert detect_kind("model.rvt") == "rvt"
    assert detect_kind("contract.docx") == "other"
    assert detect_kind("noext") == "other"


def test_extract_other_kind_returns_failed():
    result = extract(filename="contract.docx", data=b"hello world")
    assert isinstance(result, DrawingExtractionResult)
    assert result.kind == "other"
    assert result.extraction_status == "failed"
    assert "unsupported" in result.summary.lower()


def test_extract_requires_data_or_path():
    with pytest.raises(ValueError):
        extract(filename="foo.pdf")


# ---------------------------------------------------------------------------
# Stub extractors for deferred formats
# ---------------------------------------------------------------------------
def test_dwg_extractor_returns_failed_with_workaround():
    result = DwgExtractor().extract(filename="plan.dwg", data=b"AC1018")
    assert result.kind == "dwg"
    assert result.extraction_status == "failed"
    assert "G.4" in result.summary
    assert "DXF" in result.summary  # workaround mentioned


def test_rvt_extractor_returns_failed_with_workaround():
    result = RvtExtractor().extract(filename="model.rvt", data=b"\x00\x00\x00\x00")
    assert result.kind == "rvt"
    assert result.extraction_status == "failed"
    assert "IFC" in result.summary  # workaround mentioned


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
@pytest.fixture
def tiny_pdf_bytes() -> bytes:
    """Smallest possible valid PDF, generated with reportlab if available
    or hand-crafted otherwise."""
    try:
        from reportlab.pdfgen import canvas  # type: ignore
        import io

        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        c.drawString(72, 720, "Quill drawings test page 1: cover sheet")
        c.showPage()
        c.drawString(72, 720, "Page 2: site plan with cut/fill notes")
        c.showPage()
        c.drawString(72, 720, "Page 3: structural framing")
        c.showPage()
        c.save()
        return buf.getvalue()
    except ImportError:
        # Hand-crafted minimal PDF (1 page, no real content). pdfplumber
        # may still parse it; pypdfium2 will too.
        return (
            b"%PDF-1.4\n"
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
            b"4 0 obj << /Length 44 >> stream\n"
            b"BT /F1 12 Tf 72 720 Td (Hello Quill) Tj ET\n"
            b"endstream endobj\n"
            b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
            b"xref\n0 6\n0000000000 65535 f\n0000000010 00000 n\n"
            b"0000000060 00000 n\n0000000110 00000 n\n0000000210 00000 n\n0000000260 00000 n\n"
            b"trailer << /Size 6 /Root 1 0 R >>\n"
            b"startxref\n330\n%%EOF\n"
        )


def test_pdf_extract_basic(tiny_pdf_bytes):
    result = extract(filename="tiny.pdf", data=tiny_pdf_bytes)
    assert result.kind == "pdf"
    # Either the libs are installed and we get a real result, or they're
    # not and we still get a structured result with status partial/failed.
    assert result.extraction_status in {"ok", "partial", "failed"}
    assert isinstance(result.entities, dict)
    assert "page_count" in result.entities
    if result.extraction_status == "ok":
        assert result.entities["page_count"] >= 1
        assert isinstance(result.renders, list)
        # tiny pdf may not yield renders if pypdfium2 is missing
    if result.errors:
        # Errors recorded should always be strings.
        for e in result.errors:
            assert isinstance(e, str)


def test_pdf_summary_well_formed(tiny_pdf_bytes):
    result = extract(filename="tiny.pdf", data=tiny_pdf_bytes)
    assert result.summary
    assert "PDF" in result.summary


# ---------------------------------------------------------------------------
# IFC
# ---------------------------------------------------------------------------
_MIN_IFC = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION (('ViewDefinition [CoordinationView]'), '2;1');
FILE_NAME ('test.ifc', '2026-05-09T00:00:00', ('Quill Test'), ('Quill'), 'IfcOpenShell', '0.7', '');
FILE_SCHEMA (('IFC4'));
ENDSEC;
DATA;
#1 = IFCPERSON($,$,'Test',$,$,$,$,$);
#2 = IFCORGANIZATION($,'Quill',$,$,$);
#3 = IFCPERSONANDORGANIZATION(#1,#2,$);
#4 = IFCAPPLICATION(#2,'0.7','IfcOpenShell','io');
#5 = IFCOWNERHISTORY(#3,#4,$,.ADDED.,$,$,$,1716000000);
#6 = IFCPROJECT('1abc',#5,'Test',$,$,$,$,$,$);
#7 = IFCSITE('2def',#5,'Site',$,$,$,$,$,.ELEMENT.,$,$,$,$,$);
#8 = IFCBUILDING('3ghi',#5,'Building',$,$,$,$,$,.ELEMENT.,$,$,$);
#9 = IFCBUILDINGSTOREY('4jkl',#5,'L1',$,$,$,$,$,.ELEMENT.,$);
ENDSEC;
END-ISO-10303-21;
"""


def test_ifc_extract_minimal_file():
    pytest.importorskip("ifcopenshell")
    result = extract(filename="tiny.ifc", data=_MIN_IFC.encode("utf-8"))
    assert result.kind == "ifc"
    # Minimal IFC may yield zero entities of interest \u2014 status is partial.
    assert result.extraction_status in {"ok", "partial"}
    assert isinstance(result.entities, dict)
    assert "IFC" in result.summary
    # IfcBuildingStorey is one of our counted classes; should appear.
    if "IfcBuildingStorey" in result.entities:
        assert result.entities["IfcBuildingStorey"] >= 1


def test_ifc_handles_invalid_input():
    pytest.importorskip("ifcopenshell")
    result = extract(filename="bad.ifc", data=b"not an ifc file")
    assert result.kind == "ifc"
    assert result.extraction_status == "failed"
    assert result.errors


def test_ifc_no_lib_installed_returns_failed(monkeypatch):
    """If ifcopenshell isn't installed we still get a structured failure result."""
    import sys

    real_ifc = sys.modules.pop("ifcopenshell", None)
    monkeypatch.setitem(sys.modules, "ifcopenshell", None)
    try:
        result = extract(filename="x.ifc", data=b"junk")
        assert result.kind == "ifc"
        assert result.extraction_status == "failed"
        assert any("ifcopenshell" in e for e in result.errors)
    finally:
        if real_ifc is not None:
            sys.modules["ifcopenshell"] = real_ifc
        else:
            sys.modules.pop("ifcopenshell", None)


# ---------------------------------------------------------------------------
# DXF
# ---------------------------------------------------------------------------
def _build_tiny_dxf_bytes() -> bytes:
    """Build a tiny valid DXF using ezdxf (if available)."""
    try:
        import ezdxf  # type: ignore
    except ImportError:
        return b""
    import io

    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()
    doc.layers.add(name="C-GRADE", color=2)
    doc.layers.add(name="A-WALL", color=3)
    msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "C-GRADE"})
    msp.add_line((0, 0), (0, 100), dxfattribs={"layer": "A-WALL"})
    msp.add_circle((50, 50), 25, dxfattribs={"layer": "A-WALL"})
    msp.add_text("Site plan", dxfattribs={"layer": "C-GRADE"}).set_placement((10, 10))

    buf = io.StringIO()
    doc.write(buf, fmt="asc")
    return buf.getvalue().encode("latin-1")


def test_dxf_extract_basic():
    pytest.importorskip("ezdxf")
    data = _build_tiny_dxf_bytes()
    if not data:
        pytest.skip("ezdxf unavailable to build fixture")
    result = extract(filename="tiny.dxf", data=data)
    assert result.kind == "dxf"
    assert result.extraction_status == "ok"
    assert "C-GRADE" in result.entities["layers"]
    assert "A-WALL" in result.entities["layers"]
    counts = result.entities["entity_counts"]
    assert counts.get("LINE", 0) >= 2
    assert counts.get("CIRCLE", 0) >= 1
    assert "DXF" in result.summary
    assert "layers" in result.summary


def test_dxf_handles_invalid_input():
    pytest.importorskip("ezdxf")
    result = extract(filename="bad.dxf", data=b"not a dxf at all")
    assert result.kind == "dxf"
    assert result.extraction_status == "failed"


# ---------------------------------------------------------------------------
# Result dataclass behavior
# ---------------------------------------------------------------------------
def test_to_manifest_entry_shape():
    r = DrawingExtractionResult(
        filename="x.pdf",
        kind="pdf",
        size_bytes=42,
        extraction_status="ok",
        summary="PDF: 5 pages",
    )
    m = r.to_manifest_entry()
    assert m["filename"] == "x.pdf"
    assert m["kind"] == "pdf"
    assert m["size_bytes"] == 42
    assert m["extraction_status"] == "ok"
    assert m["extraction_summary"].startswith("PDF")
