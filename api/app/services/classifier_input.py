"""Shared classifier-input builder — Phase G.5.

Pure function, no I/O. Produces the input payload shape consumed by the
``design-classifier`` agent.

Used by:
- ``api/scripts/smoke_estimate_pipeline.py`` (smoke / dev)
- ``runtime/runtime/classification_dispatcher.py`` (production daemon)

Accepts both *object-style* results (``DrawingExtractionResult`` attributes)
and *dict-style* results (deserialized from blob storage JSON), so the two
callers don't need to pre-convert.
"""

from __future__ import annotations

from typing import Any


def _attr(r: Any, key: str, default: Any = None) -> Any:
    """Tolerant attribute-or-key accessor."""
    if isinstance(r, dict):
        return r.get(key, default)
    return getattr(r, key, default)


def build_classifier_input(
    extraction_results: list[Any],
    project_label: str = "",
    notes: str = "",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shape a list of extraction results into a design-classifier input payload.

    Parameters
    ----------
    extraction_results:
        A list of extraction results.  Each element may be either a
        ``DrawingExtractionResult`` object (attributes) or a plain ``dict``
        loaded from the extracted JSON blob stored at
        ``estimates/<upload_id>/extracted/<filename>.json``.
    project_label:
        Human-readable label forwarded to the classifier.
    notes:
        Optional free-text notes forwarded to the classifier.
    context:
        Optional context dict forwarded to the classifier (project type,
        size, geography, etc.).

    Returns
    -------
    dict
        The ready-to-submit payload for the ``design-classifier`` agent.
    """
    files: list[dict[str, Any]] = []
    for r in extraction_results:
        filename = _attr(r, "filename", "")
        kind = _attr(r, "kind", "")
        size_bytes = _attr(r, "size_bytes", 0)
        extraction_status = _attr(r, "extraction_status", "")
        # dict blobs store the full summary under "summary"; objects expose .summary
        extraction_summary: str = (
            _attr(r, "summary") or _attr(r, "extraction_summary") or ""
        )
        entities: dict[str, Any] = _attr(r, "entities") or {}
        quantities: dict[str, Any] = _attr(r, "quantities") or {}
        renders: list[Any] = _attr(r, "renders") or []

        entry: dict[str, Any] = {
            "filename": filename,
            "kind": kind,
            "size_bytes": size_bytes,
            "extraction_status": extraction_status,
            "extraction_summary": extraction_summary,
        }
        if kind == "pdf":
            entry["page_count"] = (
                entities.get("page_count", 0) if isinstance(entities, dict) else 0
            )
            # Cap renders to 3 for cost / token control
            entry["renders"] = renders[:3]
            entry["extracted_text_excerpts"] = (
                entities.get("text_excerpts", [])[:5]
                if isinstance(entities, dict)
                else []
            )
        elif kind == "ifc":
            entry["ifc_entities"] = entities
            entry["ifc_quantities"] = quantities
        files.append(entry)

    return {
        "project_label": project_label,
        "notes": notes,
        "uploaded_files": files,
        "context": context or {},
    }


__all__ = ["build_classifier_input"]
