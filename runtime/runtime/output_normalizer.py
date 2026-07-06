"""Artifact output normalizer — Sprint 4 (KI Phase G.4 #5).

Repairs the *documented, known-benign* LLM output quirks that were causing
schema validation failures for otherwise-correct artifacts:

1. ``summary`` longer than ``pm_artifact_base``'s 280-char cap
   (seen from ``design-classifier``) → clamped at a word boundary with a
   trailing ellipsis.
2. Citation objects that carry ``purpose`` instead of the preferred ``kind``
   (seen from ``estimator-scheduler``) → ``kind`` is backfilled from
   ``purpose``. Citations with a ``ref`` but neither descriptor get
   ``kind: "other"``.
3. Free-form evidence ``category`` labels from ``design-classifier``
   (e.g. invented enum values, mixed case, spaces) → normalized to
   ``snake_case`` and clamped to the schema's 64-char cap.

The normalizer is deliberately conservative:

- It only touches dicts that look like PM artifacts (have ``artifact_type``).
- It never removes information — it only clamps lengths and backfills
  aliases the schema documents as equivalent.
- Every repair is reported so callers can log what was changed.
"""

from __future__ import annotations

from typing import Any

# pm_artifact_base.schema.json caps.
SUMMARY_MAX_CHARS = 280
DESCRIPTOR_MAX_CHARS = 64  # citation.kind / citation.purpose / evidence.category


def _clamp_text(text: str, limit: int) -> str:
    """Clamp ``text`` to ``limit`` chars, preferring a word boundary,
    appending a single-char ellipsis so the result stays within ``limit``."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    # Only back off to the word boundary if it doesn't cost us most of the text.
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip() + "\u2026"


def _snake_case_label(label: str, limit: int = DESCRIPTOR_MAX_CHARS) -> str:
    cleaned = "_".join(label.strip().lower().split())
    return cleaned[:limit] or "other"


def _normalize_citations(citations: Any, fixes: list[str]) -> None:
    if not isinstance(citations, list):
        return
    for i, cit in enumerate(citations):
        if not isinstance(cit, dict):
            continue
        purpose = cit.get("purpose")
        kind = cit.get("kind")
        if not isinstance(kind, str) or not kind:
            if isinstance(purpose, str) and purpose:
                cit["kind"] = purpose[:DESCRIPTOR_MAX_CHARS]
                fixes.append(f"citations[{i}].kind_backfilled_from_purpose")
            elif cit.get("ref"):
                cit["kind"] = "other"
                fixes.append(f"citations[{i}].kind_defaulted_other")
        elif len(kind) > DESCRIPTOR_MAX_CHARS:
            cit["kind"] = kind[:DESCRIPTOR_MAX_CHARS]
            fixes.append(f"citations[{i}].kind_clamped")
        if isinstance(purpose, str) and len(purpose) > DESCRIPTOR_MAX_CHARS:
            cit["purpose"] = purpose[:DESCRIPTOR_MAX_CHARS]
            fixes.append(f"citations[{i}].purpose_clamped")


def _normalize_evidence_categories(metadata: Any, fixes: list[str]) -> None:
    if not isinstance(metadata, dict):
        return
    evidence = metadata.get("supporting_evidence")
    if not isinstance(evidence, list):
        return
    for i, item in enumerate(evidence):
        if not isinstance(item, dict):
            continue
        cat = item.get("category")
        if isinstance(cat, str) and cat:
            normalized = _snake_case_label(cat)
            if normalized != cat:
                item["category"] = normalized
                fixes.append(f"supporting_evidence[{i}].category_normalized")


def normalize_artifact_output(output: Any) -> tuple[Any, list[str]]:
    """Repair known-benign schema deviations in a PM artifact dict.

    Returns ``(output, fixes)`` where ``fixes`` is a list of human-readable
    repair tags (empty when nothing was changed). ``output`` is mutated in
    place and returned for convenience. Non-artifact payloads pass through
    untouched.
    """
    fixes: list[str] = []
    if not isinstance(output, dict) or "artifact_type" not in output:
        return output, fixes

    summary = output.get("summary")
    if isinstance(summary, str) and len(summary) > SUMMARY_MAX_CHARS:
        output["summary"] = _clamp_text(summary, SUMMARY_MAX_CHARS)
        fixes.append("summary_clamped")

    _normalize_citations(output.get("citations"), fixes)
    _normalize_evidence_categories(output.get("metadata"), fixes)

    return output, fixes


__all__ = [
    "normalize_artifact_output",
    "SUMMARY_MAX_CHARS",
    "DESCRIPTOR_MAX_CHARS",
]
