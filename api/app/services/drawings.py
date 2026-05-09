"""Drawing extraction service — Phase G.1.

Reads uploaded design files (PDF, IFC, DXF for v0.1; DWG/RVT deferred to G.4)
and produces a `DrawingExtractionResult` containing:

- `kind`: file kind (pdf | ifc | dxf | dwg | rvt | other)
- `summary`: plain-English summary used by downstream agents
- `entities`: structured per-format entity counts/quantities
- `renders`: up to 5 base64-encoded PNG page renders (PDF only for v0.1)
- `extraction_status`: ok | partial | failed
- `errors`: optional list of free-form error strings

Heavy library imports (ifcopenshell, ezdxf, pdfplumber, pypdfium2) are done
lazily inside extractor methods so the API process can boot without them
installed (they're optional for tests that don't exercise the format).

This service is **storage-agnostic**. It accepts raw bytes (or a Path) and
returns the result as a Python object. Persistence (MinIO keys, DB rows)
lives in `services.estimates`.
"""

from __future__ import annotations

import base64
import io
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger("quill.drawings")


FileKind = Literal["pdf", "ifc", "dwg", "dxf", "rvt", "other"]
ExtractionStatus = Literal["ok", "partial", "failed"]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass
class DrawingExtractionResult:
    """Output of a drawing extraction pass.

    Mirrors the `uploaded_files[]` entries that the design-classifier and
    estimator-scheduler agents expect, plus a `renders` array for vision.
    """

    filename: str
    kind: FileKind
    size_bytes: int
    extraction_status: ExtractionStatus
    summary: str = ""
    entities: dict[str, Any] = field(default_factory=dict)
    quantities: dict[str, Any] = field(default_factory=dict)
    renders: list[dict[str, str]] = field(default_factory=list)
    """List of {page: int|str, image_b64: str, caption: str} dicts."""
    errors: list[str] = field(default_factory=list)

    def to_manifest_entry(self) -> dict[str, Any]:
        """Slimmed-down dict matching the agents' uploaded_files schema."""
        return {
            "filename": self.filename,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "extraction_status": self.extraction_status,
            "extraction_summary": self.summary[:4000],
        }


# ---------------------------------------------------------------------------
# Kind detection
# ---------------------------------------------------------------------------
_KIND_BY_EXT: dict[str, FileKind] = {
    ".pdf": "pdf",
    ".ifc": "ifc",
    ".dxf": "dxf",
    ".dwg": "dwg",
    ".rvt": "rvt",
}


def detect_kind(filename: str) -> FileKind:
    ext = os.path.splitext(filename.lower())[1]
    return _KIND_BY_EXT.get(ext, "other")


# ---------------------------------------------------------------------------
# Extractor base
# ---------------------------------------------------------------------------
class _BaseExtractor:
    """Shared scaffolding for per-format extractors."""

    kind: FileKind = "other"

    MAX_RENDERS: int = 5
    MAX_RENDER_BYTES: int = 600_000  # 600 KB cap per render

    def extract(
        self,
        *,
        filename: str,
        data: bytes | None = None,
        path: Path | None = None,
    ) -> DrawingExtractionResult:
        size = len(data) if data is not None else (path.stat().st_size if path else 0)
        result = DrawingExtractionResult(
            filename=filename,
            kind=self.kind,
            size_bytes=size,
            extraction_status="failed",
        )
        try:
            self._extract_into(result, data=data, path=path)
        except Exception as exc:  # noqa: BLE001
            log.exception("drawings.extract_failed kind=%s file=%s", self.kind, filename)
            result.extraction_status = "failed"
            result.errors.append(f"{type(exc).__name__}: {exc}")
            if not result.summary:
                result.summary = (
                    f"Extraction failed for {self.kind} file {filename}. "
                    f"Error: {type(exc).__name__}."
                )
        return result

    def _extract_into(
        self,
        result: DrawingExtractionResult,
        *,
        data: bytes | None,
        path: Path | None,
    ) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
class PdfExtractor(_BaseExtractor):
    kind: FileKind = "pdf"

    def _extract_into(
        self,
        result: DrawingExtractionResult,
        *,
        data: bytes | None,
        path: Path | None,
    ) -> None:
        # We try pdfplumber first for text; pypdfium2 second for renders.
        # Both are optional dependencies — if neither is installed we still
        # produce a result with extraction_status='partial'.
        page_count = 0
        text_excerpts: list[dict[str, str]] = []
        render_pages: list[int] = []
        partial = False

        # Text + page count via pdfplumber
        try:
            import pdfplumber  # type: ignore

            buf = io.BytesIO(data) if data is not None else open(path, "rb")  # noqa: SIM115
            try:
                with pdfplumber.open(buf) as pdf:
                    page_count = len(pdf.pages)
                    sample_indexes = self._sample_page_indexes(page_count, count=5)
                    for i in sample_indexes:
                        try:
                            page = pdf.pages[i]
                            text = (page.extract_text() or "").strip()
                            text = text[:1500]
                            if text:
                                text_excerpts.append({
                                    "ref": f"page {i + 1}",
                                    "text": text,
                                })
                            render_pages.append(i)
                        except Exception as exc:  # noqa: BLE001
                            partial = True
                            result.errors.append(f"page {i + 1} text extract: {exc}")
            finally:
                if not isinstance(buf, io.BytesIO):
                    buf.close()
        except ImportError:
            partial = True
            result.errors.append("pdfplumber not installed; text extraction skipped")
        except Exception as exc:  # noqa: BLE001
            partial = True
            result.errors.append(f"pdfplumber error: {exc}")

        # Renders via pypdfium2
        try:
            import pypdfium2 as pdfium  # type: ignore

            buf2_data = data if data is not None else (path.read_bytes() if path else b"")
            doc = pdfium.PdfDocument(buf2_data)
            try:
                actual_page_count = len(doc)
                if page_count == 0:
                    page_count = actual_page_count
                sample = render_pages or self._sample_page_indexes(actual_page_count, count=5)
                for i in sample[: self.MAX_RENDERS]:
                    if i < 0 or i >= actual_page_count:
                        continue
                    try:
                        page = doc[i]
                        # Render at modest scale to keep payload small.
                        bitmap = page.render(scale=0.75).to_pil()
                        out = io.BytesIO()
                        bitmap.save(out, format="PNG", optimize=True)
                        png = out.getvalue()
                        if len(png) > self.MAX_RENDER_BYTES:
                            # Re-render at lower scale.
                            bitmap = page.render(scale=0.5).to_pil()
                            out = io.BytesIO()
                            bitmap.save(out, format="PNG", optimize=True)
                            png = out.getvalue()
                        b64 = base64.b64encode(png).decode("ascii")
                        result.renders.append({
                            "page": i + 1,
                            "image_b64": b64,
                            "caption": f"Page {i + 1}",
                        })
                    except Exception as exc:  # noqa: BLE001
                        partial = True
                        result.errors.append(f"page {i + 1} render: {exc}")
            finally:
                doc.close()
        except ImportError:
            partial = True
            result.errors.append("pypdfium2 not installed; page renders skipped")
        except Exception as exc:  # noqa: BLE001
            partial = True
            result.errors.append(f"pypdfium2 error: {exc}")

        result.entities = {
            "page_count": page_count,
            "text_excerpts": text_excerpts,
        }
        result.quantities = {}
        result.summary = self._make_summary(
            page_count=page_count,
            excerpts=len(text_excerpts),
            renders=len(result.renders),
        )
        if page_count == 0 and not text_excerpts and not result.renders:
            result.extraction_status = "failed"
        elif partial or not result.renders:
            result.extraction_status = "partial"
        else:
            result.extraction_status = "ok"

    @staticmethod
    def _sample_page_indexes(n: int, *, count: int = 5) -> list[int]:
        if n <= 0:
            return []
        if n <= count:
            return list(range(n))
        # Even spread: first, last, and 3 evenly between.
        step = max(1, n // count)
        idxs = list(range(0, n, step))[:count]
        if (n - 1) not in idxs:
            idxs[-1] = n - 1
        return idxs

    @staticmethod
    def _make_summary(*, page_count: int, excerpts: int, renders: int) -> str:
        parts: list[str] = []
        parts.append(f"PDF: {page_count} pages")
        if excerpts:
            parts.append(f"{excerpts} text excerpt(s) sampled")
        if renders:
            parts.append(f"{renders} page render(s) generated")
        return "; ".join(parts) + "."


# ---------------------------------------------------------------------------
# IFC
# ---------------------------------------------------------------------------
class IfcExtractor(_BaseExtractor):
    kind: FileKind = "ifc"

    # Entity classes worth counting up-front.
    _COUNT_CLASSES = (
        "IfcWall", "IfcSlab", "IfcColumn", "IfcBeam", "IfcDoor",
        "IfcWindow", "IfcStair", "IfcRoof", "IfcSpace", "IfcBuildingStorey",
        "IfcChiller", "IfcUnitaryEquipment", "IfcAirTerminal",
        "IfcFlowController", "IfcDistributionElement", "IfcCovering",
    )

    def _extract_into(
        self,
        result: DrawingExtractionResult,
        *,
        data: bytes | None,
        path: Path | None,
    ) -> None:
        try:
            import ifcopenshell  # type: ignore
        except ImportError:
            result.summary = "IFC: ifcopenshell not installed; extraction skipped."
            result.errors.append("ifcopenshell not installed")
            result.extraction_status = "failed"
            return

        # ifcopenshell.open accepts a path; if we have bytes, write a temp file.
        import tempfile

        tmp: tempfile._TemporaryFileWrapper | None = None
        target_path: str
        if path is not None:
            target_path = str(path)
        else:
            tmp = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
            tmp.write(data or b"")
            tmp.close()
            target_path = tmp.name

        try:
            try:
                model = ifcopenshell.open(target_path)
            except Exception as exc:  # noqa: BLE001
                result.summary = f"IFC: open failed ({type(exc).__name__})."
                result.errors.append(f"open: {exc}")
                result.extraction_status = "failed"
                return

            entities: dict[str, int] = {}
            for cls in self._COUNT_CLASSES:
                try:
                    cnt = len(model.by_type(cls))
                except Exception:  # noqa: BLE001
                    cnt = 0
                if cnt:
                    entities[cls] = cnt

            # Quantity rollups (best-effort)
            quantities: dict[str, Any] = {}
            try:
                area_total = 0.0
                volume_total = 0.0
                for q in model.by_type("IfcQuantityArea"):
                    try:
                        area_total += float(q.AreaValue or 0.0)
                    except Exception:  # noqa: BLE001
                        continue
                for q in model.by_type("IfcQuantityVolume"):
                    try:
                        volume_total += float(q.VolumeValue or 0.0)
                    except Exception:  # noqa: BLE001
                        continue
                if area_total:
                    # IFC areas come in m^2; convert to ft^2 (1 m^2 = 10.7639 ft^2)
                    quantities["IfcQuantityArea_total_sf"] = round(area_total * 10.7639, 1)
                    quantities["IfcQuantityArea_total_m2"] = round(area_total, 2)
                if volume_total:
                    # Convert m^3 to CY (1 m^3 = 1.30795 CY)
                    quantities["IfcQuantityVolume_total_cy"] = round(volume_total * 1.30795, 1)
                    quantities["IfcQuantityVolume_total_m3"] = round(volume_total, 2)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"quantity rollup: {exc}")

            try:
                schema = model.schema
            except Exception:  # noqa: BLE001
                schema = "?"

            result.entities = entities
            result.quantities = quantities
            total = sum(entities.values())
            schema_part = f"schema {schema}" if schema else ""
            entity_part = f"{total} entities" if total else "no entities of interest detected"
            result.summary = (
                f"IFC: {schema_part}; {entity_part}; "
                f"key counts: {entities or '{}'}; "
                f"quantities: {quantities or '{}'}."
            )
            if total > 0:
                result.extraction_status = "ok"
            else:
                result.extraction_status = "partial"
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp.name)
                except Exception:  # noqa: BLE001
                    pass


# ---------------------------------------------------------------------------
# DXF
# ---------------------------------------------------------------------------
class DxfExtractor(_BaseExtractor):
    kind: FileKind = "dxf"

    def _extract_into(
        self,
        result: DrawingExtractionResult,
        *,
        data: bytes | None,
        path: Path | None,
    ) -> None:
        try:
            import ezdxf  # type: ignore
        except ImportError:
            result.summary = "DXF: ezdxf not installed; extraction skipped."
            result.errors.append("ezdxf not installed")
            result.extraction_status = "failed"
            return

        try:
            if path is not None:
                doc = ezdxf.readfile(str(path))
            else:
                # ezdxf accepts a string IO; decode latin-1 to be safe vs. encodings.
                buf = io.StringIO((data or b"").decode("latin-1", errors="replace"))
                doc = ezdxf.read(buf)
        except Exception as exc:  # noqa: BLE001
            result.summary = f"DXF: open failed ({type(exc).__name__})."
            result.errors.append(f"open: {exc}")
            result.extraction_status = "failed"
            return

        try:
            layers = sorted({lyr.dxf.name for lyr in doc.layers})
            msp = doc.modelspace()
            entity_counts: dict[str, int] = {}
            for ent in msp:
                t = ent.dxftype()
                entity_counts[t] = entity_counts.get(t, 0) + 1
            block_count = sum(1 for _ in doc.blocks if _.name not in {"*MODEL_SPACE", "*PAPER_SPACE"})
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"DXF parse: {exc}")
            result.extraction_status = "partial"
            result.summary = f"DXF: parse partial ({type(exc).__name__})."
            return

        result.entities = {
            "layers": layers[:200],
            "entity_counts": entity_counts,
            "block_count": block_count,
        }
        layer_excerpt = ", ".join(layers[:10]) + (", ..." if len(layers) > 10 else "")
        total_entities = sum(entity_counts.values())
        result.summary = (
            f"DXF: {len(layers)} layers ({layer_excerpt}); "
            f"{total_entities} entities; {block_count} blocks."
        )
        if total_entities > 0:
            result.extraction_status = "ok"
        else:
            result.extraction_status = "partial"


# ---------------------------------------------------------------------------
# DWG — Phase G.4
# ---------------------------------------------------------------------------
#
# Native DWG parsing is non-trivial: libredwg is not in Homebrew on macOS
# and building from source is brittle. Instead we look for the ODA File
# Converter binary (a free Autodesk tool that converts DWG → DXF) on PATH.
# If present, we shell out to it, read back the produced DXF, and re-extract
# via DxfExtractor. If not present, we return a friendly
# extraction_status='needs_conversion' with instructions.
# ---------------------------------------------------------------------------
import shutil
import subprocess
import tempfile

# Common install locations for ODA File Converter (mac + linux defaults
# documented at https://www.opendesign.com/guestfiles/oda_file_converter).
_ODA_CANDIDATE_BINARIES = (
    "ODAFileConverter",                                                # PATH lookup
    "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter",
    "/usr/bin/ODAFileConverter",
    "/usr/local/bin/ODAFileConverter",
)

_DWG_NEEDS_CONVERSION_MESSAGE = (
    "DWG files need conversion. Install ODA File Converter (free at "
    "https://www.opendesign.com/guestfiles/oda_file_converter) and ensure the "
    "`ODAFileConverter` binary is on PATH, or convert this file to DXF in "
    "any CAD tool (AutoCAD, BricsCAD, FreeCAD, LibreCAD) and re-upload the "
    "DXF."
)


def _find_oda_binary() -> str | None:
    """Return path to the ODA File Converter binary, or None if not found."""
    for cand in _ODA_CANDIDATE_BINARIES:
        if cand == "ODAFileConverter":
            found = shutil.which(cand)
            if found:
                return found
        elif os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


class DwgExtractor(_BaseExtractor):
    """DWG → DXF (via ODA File Converter) → DxfExtractor.

    If ODA File Converter is not installed, returns a friendly
    `extraction_status='needs_conversion'` (note: this status is reported
    in the result; the dataclass `extraction_status` field is one of
    ok|partial|failed at the schema level, so we use 'failed' as the
    underlying status and surface 'needs_conversion' in the summary +
    errors list).
    """

    kind: FileKind = "dwg"

    # ODA File Converter CLI signature (it's a TUI dialog tool when run
    # without args; when run with positional args it operates headless).
    # Args: <input_dir> <output_dir> <output_version> <output_filetype>
    #       <recurse> <audit> [<input_filter>]
    # output_version: "ACAD2018" works broadly; output_filetype: 1=DXF, 2=DWG
    _ODA_OUTPUT_VERSION = "ACAD2018"
    _ODA_OUTPUT_FILETYPE = "1"  # DXF

    def _extract_into(
        self,
        result: DrawingExtractionResult,
        *,
        data: bytes | None,
        path: Path | None,
    ) -> None:
        oda = _find_oda_binary()
        if not oda:
            result.summary = _DWG_NEEDS_CONVERSION_MESSAGE
            result.errors.append("oda_file_converter_not_found")
            # Surface the soft-status on the entities dict so callers and
            # downstream agents can detect the conversion-needed case
            # without parsing the human-readable summary.
            result.entities = {"extraction_status_detail": "needs_conversion"}
            result.extraction_status = "failed"
            return

        # ODA File Converter operates on directories, not single files, so
        # we set up an isolated input dir with the DWG copied in, run the
        # converter, and pick up the resulting DXF from the output dir.
        with tempfile.TemporaryDirectory(prefix="quill_dwg_in_") as in_dir, \
             tempfile.TemporaryDirectory(prefix="quill_dwg_out_") as out_dir:
            in_path = Path(in_dir) / "input.dwg"
            if data is not None:
                in_path.write_bytes(data)
            elif path is not None:
                in_path.write_bytes(Path(path).read_bytes())
            else:
                result.summary = "DWG: no data or path provided."
                result.errors.append("no_input")
                result.extraction_status = "failed"
                return

            try:
                proc = subprocess.run(  # noqa: S603 — trusted local binary
                    [
                        oda,
                        in_dir,
                        out_dir,
                        self._ODA_OUTPUT_VERSION,
                        self._ODA_OUTPUT_FILETYPE,
                        "0",  # recurse
                        "1",  # audit
                    ],
                    capture_output=True,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                result.summary = (
                    "DWG: ODA File Converter timed out after 60s. The DWG "
                    "may be too large or corrupted. Convert to DXF manually "
                    "and re-upload."
                )
                result.errors.append("oda_timeout")
                result.extraction_status = "failed"
                return
            except OSError as exc:
                result.summary = f"DWG: ODA File Converter failed to start ({exc})."
                result.errors.append(f"oda_oserror: {exc}")
                result.extraction_status = "failed"
                return

            if proc.returncode != 0:
                stderr = (proc.stderr or b"").decode("utf-8", errors="replace")[:400]
                result.summary = (
                    "DWG: ODA File Converter returned a non-zero exit "
                    f"code ({proc.returncode}). Try converting to DXF manually."
                )
                result.errors.append(f"oda_returncode={proc.returncode}: {stderr}")
                result.extraction_status = "failed"
                return

            # Pick up the resulting DXF (ODA names it <stem>.dxf in out_dir).
            dxf_files = list(Path(out_dir).glob("*.dxf"))
            if not dxf_files:
                result.summary = (
                    "DWG: ODA File Converter ran but produced no DXF output."
                )
                result.errors.append("oda_no_dxf_produced")
                result.extraction_status = "failed"
                return

            dxf_path = dxf_files[0]
            inner = DxfExtractor().extract(
                filename=result.filename, path=dxf_path
            )
            # Mirror the inner DXF result onto our dwg result so the
            # caller still sees kind='dwg'.
            result.entities = inner.entities
            result.quantities = inner.quantities
            result.renders = inner.renders
            result.errors.extend(inner.errors)
            result.extraction_status = inner.extraction_status
            result.summary = (
                f"DWG (converted to DXF via ODA File Converter): {inner.summary}"
            )


# ---------------------------------------------------------------------------
# RVT — Phase G.4
# ---------------------------------------------------------------------------
_RVT_NOT_CONFIGURED_MESSAGE = (
    "RVT extraction needs Autodesk APS credentials (set APS_CLIENT_ID + "
    "APS_CLIENT_SECRET in .env). Or export your RVT to IFC from Revit "
    "(File → Export → IFC) and upload the IFC instead."
)


class RvtExtractor(_BaseExtractor):
    """RVT extractor backed by the Autodesk Platform Services (APS, formerly
    Forge) Model Derivative API.

    If `APS_CLIENT_ID` and `APS_CLIENT_SECRET` are not set, returns a
    friendly 'not_configured' status with workaround instructions.
    """

    kind: FileKind = "rvt"

    def _extract_into(
        self,
        result: DrawingExtractionResult,
        *,
        data: bytes | None,
        path: Path | None,
    ) -> None:
        # Lazy import so api boot doesn't depend on httpx being available
        # for non-RVT users.
        try:
            from app.services.aps import APSClient
        except Exception as exc:  # noqa: BLE001
            result.summary = (
                f"RVT: APS client unavailable ({type(exc).__name__}). "
                + _RVT_NOT_CONFIGURED_MESSAGE
            )
            result.errors.append(f"aps_import_failed: {exc}")
            result.entities = {"extraction_status_detail": "not_configured"}
            result.extraction_status = "failed"
            return

        client = APSClient()
        if not client.is_available:
            result.summary = _RVT_NOT_CONFIGURED_MESSAGE
            result.errors.append("aps_credentials_not_set")
            result.entities = {"extraction_status_detail": "not_configured"}
            result.extraction_status = "failed"
            return

        # Real extraction path runs the APS client end-to-end. Synchronous
        # wrapper around the async client so the extractor signature is
        # uniform with the others.
        import asyncio as _asyncio
        try:
            entities, quantities = _asyncio.run(
                _run_aps_extraction(client, data=data, path=path, filename=result.filename)
            )
        except Exception as exc:  # noqa: BLE001
            result.summary = (
                f"RVT: APS extraction failed ({type(exc).__name__}: {exc}). "
                "Try exporting to IFC from Revit and re-uploading."
            )
            result.errors.append(f"aps_failed: {exc}")
            result.extraction_status = "failed"
            return

        result.entities = entities
        result.quantities = quantities
        elem_count = len(entities.get("elements", []))
        result.summary = (
            f"RVT (via Autodesk APS Model Derivative): {elem_count} elements; "
            f"quantities: {sorted(quantities.keys())[:6]}."
        )
        result.extraction_status = "ok" if elem_count > 0 else "partial"


async def _run_aps_extraction(
    client,  # APSClient — typed loosely to avoid circular import
    *,
    data: bytes | None,
    path: Path | None,
    filename: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    body = data if data is not None else (path.read_bytes() if path else b"")
    await client.authenticate()
    urn = await client.upload(body, filename)
    await client.start_translation(urn)
    await client.poll_translation(urn, timeout_s=60.0)
    metadata = await client.get_metadata(urn)
    quantities = await client.get_quantities(urn)
    return metadata, quantities


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
_EXTRACTORS: dict[FileKind, type[_BaseExtractor]] = {
    "pdf": PdfExtractor,
    "ifc": IfcExtractor,
    "dxf": DxfExtractor,
    "dwg": DwgExtractor,
    "rvt": RvtExtractor,
}


def extract(
    *,
    filename: str,
    data: bytes | None = None,
    path: Path | None = None,
) -> DrawingExtractionResult:
    """Extract a single design file. Returns a DrawingExtractionResult.

    Either `data` (bytes) or `path` (Path) must be provided.
    """
    if data is None and path is None:
        raise ValueError("extract() requires either data or path")
    kind = detect_kind(filename)
    klass = _EXTRACTORS.get(kind)
    if klass is None:
        size = len(data) if data is not None else (path.stat().st_size if path else 0)
        return DrawingExtractionResult(
            filename=filename,
            kind="other",
            size_bytes=size,
            extraction_status="failed",
            summary=f"Unsupported file extension for {filename}; v0.1 supports .pdf, .ifc, .dxf.",
            errors=["unsupported_kind"],
        )
    return klass().extract(filename=filename, data=data, path=path)


__all__ = [
    "DrawingExtractionResult",
    "FileKind",
    "ExtractionStatus",
    "PdfExtractor",
    "IfcExtractor",
    "DxfExtractor",
    "DwgExtractor",
    "RvtExtractor",
    "detect_kind",
    "extract",
]
