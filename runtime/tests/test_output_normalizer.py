"""Tests for runtime.output_normalizer — Sprint 4 (KI Phase G.4 #5)."""

from __future__ import annotations

from runtime.output_normalizer import (
    DESCRIPTOR_MAX_CHARS,
    SUMMARY_MAX_CHARS,
    normalize_artifact_output,
)


def _artifact(**overrides):
    base = {
        "artifact_type": "aace_classification",
        "artifact_id": "art-1",
        "title": "Test",
        "summary": "Short summary.",
        "body_markdown": "# body",
        "metadata": {},
        "citations": [],
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Pass-through behavior
# ---------------------------------------------------------------------------
def test_non_dict_passes_through():
    out, fixes = normalize_artifact_output(["not", "a", "dict"])
    assert out == ["not", "a", "dict"]
    assert fixes == []


def test_non_artifact_dict_passes_through():
    payload = {"summary": "x" * 500}
    out, fixes = normalize_artifact_output(payload)
    assert out["summary"] == "x" * 500  # untouched — no artifact_type
    assert fixes == []


def test_clean_artifact_unchanged():
    art = _artifact()
    before = dict(art)
    out, fixes = normalize_artifact_output(art)
    assert out == before
    assert fixes == []


# ---------------------------------------------------------------------------
# KI G.4.5 bug 1: design-classifier summary over 280 chars
# ---------------------------------------------------------------------------
def test_long_summary_clamped():
    long_summary = ("The design package supports Class 5 estimating. " * 12).strip()
    assert len(long_summary) > SUMMARY_MAX_CHARS
    out, fixes = normalize_artifact_output(_artifact(summary=long_summary))
    assert len(out["summary"]) <= SUMMARY_MAX_CHARS
    assert out["summary"].endswith("\u2026")
    assert "summary_clamped" in fixes


def test_summary_at_limit_untouched():
    exact = "y" * SUMMARY_MAX_CHARS
    out, fixes = normalize_artifact_output(_artifact(summary=exact))
    assert out["summary"] == exact
    assert fixes == []


def test_summary_clamp_prefers_word_boundary():
    words = ("alpha bravo charlie " * 30).strip()
    out, _ = normalize_artifact_output(_artifact(summary=words))
    # No mid-word cut: strip the ellipsis and the remainder must be whole words
    body = out["summary"].rstrip("\u2026").strip()
    assert body.split(" ")[-1] in ("alpha", "bravo", "charlie")


# ---------------------------------------------------------------------------
# KI G.4.5 bug 2: estimator-scheduler citations with purpose instead of kind
# ---------------------------------------------------------------------------
def test_citation_purpose_backfills_kind():
    art = _artifact(
        citations=[{"purpose": "rate_source", "ref": "RSMeans 2026 §03 30 00"}]
    )
    out, fixes = normalize_artifact_output(art)
    assert out["citations"][0]["kind"] == "rate_source"
    assert out["citations"][0]["purpose"] == "rate_source"  # preserved
    assert any("kind_backfilled_from_purpose" in f for f in fixes)


def test_citation_missing_both_descriptors_defaults_other():
    art = _artifact(citations=[{"ref": "drawing A-101"}])
    out, fixes = normalize_artifact_output(art)
    assert out["citations"][0]["kind"] == "other"
    assert any("kind_defaulted_other" in f for f in fixes)


def test_citation_with_kind_untouched():
    art = _artifact(citations=[{"kind": "drawing", "ref": "A-101"}])
    out, fixes = normalize_artifact_output(art)
    assert out["citations"][0] == {"kind": "drawing", "ref": "A-101"}
    assert fixes == []


def test_citation_overlong_descriptors_clamped():
    long_val = "z" * (DESCRIPTOR_MAX_CHARS + 20)
    art = _artifact(citations=[{"kind": long_val, "purpose": long_val, "ref": "r"}])
    out, fixes = normalize_artifact_output(art)
    assert len(out["citations"][0]["kind"]) == DESCRIPTOR_MAX_CHARS
    assert len(out["citations"][0]["purpose"]) == DESCRIPTOR_MAX_CHARS
    assert fixes  # both clamps recorded


def test_citation_non_dict_entries_skipped():
    art = _artifact(citations=["stringy", {"kind": "rfi", "ref": "RFI-1"}])
    out, fixes = normalize_artifact_output(art)
    assert out["citations"][0] == "stringy"
    assert fixes == []


# ---------------------------------------------------------------------------
# KI G.4.5 bug 3: design-classifier free-form evidence categories
# ---------------------------------------------------------------------------
def test_evidence_category_normalized_to_snake_case():
    art = _artifact(
        metadata={
            "supporting_evidence": [
                {"category": "Civil Site Detail", "score": 0.4, "evidence": "e"},
                {"category": "bim_model_quality", "score": 0.2, "evidence": "e"},
            ]
        }
    )
    out, fixes = normalize_artifact_output(art)
    ev = out["metadata"]["supporting_evidence"]
    assert ev[0]["category"] == "civil_site_detail"
    assert ev[1]["category"] == "bim_model_quality"  # already conformant
    assert fixes == ["supporting_evidence[0].category_normalized"]


def test_evidence_category_clamped_to_64():
    art = _artifact(
        metadata={
            "supporting_evidence": [
                {"category": "q" * 100, "score": 0.1, "evidence": "e"}
            ]
        }
    )
    out, _ = normalize_artifact_output(art)
    assert len(out["metadata"]["supporting_evidence"][0]["category"]) == DESCRIPTOR_MAX_CHARS
