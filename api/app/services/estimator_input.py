"""Shared estimator-input builder — Phase G.6.

Pure function, no I/O. Produces the input payload shape consumed by the
``estimator-scheduler`` agent.

Used by:
- ``api/scripts/smoke_estimate_pipeline.py`` (smoke / dev)
- ``runtime/runtime/estimator_dispatcher.py`` (production daemon)

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


_DEFAULT_COST_LIBRARY: dict[str, Any] = {
    "version": "v0.1.0",
    "currency": "USD",
    "base_year": "2026",
    "rows": [
        {
            "csi_section": "01 00 00",
            "description": "ROM hyperscale-DC build",
            "unit": "MW",
            "unit_rate_usd": 11_500_000,
            "rate_source": "llm_estimate",
            "rate_year": 2026,
            "geographic_multiplier_for": "Central Ohio",
            "confidence": 0.45,
        },
        {
            "csi_section": "31 00 00",
            "description": "Sitework / earthwork ROM",
            "unit": "CY",
            "unit_rate_usd": 12.5,
            "rate_source": "llm_estimate",
            "rate_year": 2026,
            "confidence": 0.45,
        },
        {
            "csi_section": "26 13 13",
            "description": "MV switchgear, 15kV",
            "unit": "EA",
            "unit_rate_usd": 285_000,
            "rate_source": "llm_estimate",
            "rate_year": 2026,
            "confidence": 0.5,
        },
    ],
}


def build_estimator_input(
    extraction_results: list[Any],
    classification_artifact: dict[str, Any],
    *,
    project_label: str = "",
    project_context: dict[str, Any] | None = None,
    cost_library: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shape a list of extraction results + classification artifact into an
    estimator-scheduler input payload.

    Parameters
    ----------
    extraction_results:
        A list of extraction results.  Each element may be either a
        ``DrawingExtractionResult`` object (attributes) or a plain ``dict``
        loaded from the extracted JSON blob stored at
        ``estimates/<upload_id>/extracted/<filename>.json``.
    classification_artifact:
        The approved ``aace_classification`` artifact dict.  This is the
        ``payload.artifact`` from the approved ApprovalItem.
    project_label:
        Human-readable label forwarded to the estimator.
    project_context:
        Optional context dict (project type, size, geography, etc.).
        Defaults to an empty dict if not provided.
    cost_library:
        Optional cost library dict.  Defaults to the built-in v0.1 stub
        if not provided.

    Returns
    -------
    dict
        The ready-to-submit payload for the ``estimator-scheduler`` agent.
    """
    pdf_extracts: list[dict[str, Any]] = []
    ifc_extracts: list[dict[str, Any]] = []

    for r in extraction_results:
        kind = _attr(r, "kind", "")
        filename = _attr(r, "filename", "")
        entities = _attr(r, "entities") or {}

        if kind == "pdf":
            page_count = (
                entities.get("page_count", 0)
                if isinstance(entities, dict)
                else 0
            )
            text_excerpts = (
                entities.get("text_excerpts", [])[:5]
                if isinstance(entities, dict)
                else []
            )
            pdf_extracts.append(
                {
                    "filename": filename,
                    "page_count": page_count,
                    "extracted_text_excerpts": text_excerpts,
                }
            )
        elif kind == "ifc":
            ifc_extracts.append(
                {
                    "filename": filename,
                    "entities": entities,
                    "quantities": _attr(r, "quantities") or {},
                }
            )

    meta: dict[str, Any] = classification_artifact.get("metadata") or {}

    return {
        "project_label": project_label,
        "approved_classification": {
            "artifact_id": classification_artifact.get("artifact_id"),
            "class": meta.get("class"),
            "design_maturity_estimate_pct": meta.get(
                "design_maturity_estimate_pct"
            ),
            "uploaded_files": meta.get("uploaded_files") or [],
            "supporting_evidence": meta.get("supporting_evidence") or [],
            "design_disciplines_detected": meta.get(
                "design_disciplines_detected"
            )
            or [],
            "missing_for_next_class": meta.get("missing_for_next_class") or [],
        },
        "extracted_scope": {
            "pdf": pdf_extracts,
            "ifc": ifc_extracts,
        },
        "cost_library": cost_library if cost_library is not None else _DEFAULT_COST_LIBRARY,
        "project_context": project_context or {},
    }


__all__ = ["build_estimator_input"]
