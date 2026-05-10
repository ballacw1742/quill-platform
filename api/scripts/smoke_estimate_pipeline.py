"""Phase G.4 — End-to-end smoke test against the LIVE Anthropic API.

What this does:
  1. Generates two synthetic test fixtures inline:
       a. A 1-page PDF concept site plan describing a 4-building hyperscale
          data center campus.
       b. A small IFC file with a few walls + spaces + quantities.
  2. Runs both files through the in-process drawing extraction pipeline
     and confirms the manifest is sane.
  3. Calls the design-classifier agent against the live Anthropic API.
       - Captures classification class, confidence, missing-info list.
  4. Calls the estimator-scheduler agent against the live Anthropic API
     using the (auto-approved-for-smoke) classification as input.
       - Captures top-5 cost rows, top-5 schedule activities, totals.
  5. Validates both outputs against their JSON schemas.

Spend cap: aborts after a single agent run if it exceeds $3, or if total
cumulative cost exceeds $5.

Run:
    cd /Users/charlesmitchell/.openclaw/workspace/quill-platform
    source .venv/bin/activate
    cd api && PYTHONPATH=. python scripts/smoke_estimate_pipeline.py

Output: prints verbatim agent JSON to stdout and writes to
api/scripts/smoke_results/<utc-stamp>/.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure both api/app and runtime are importable when run from api/.
_HERE = Path(__file__).resolve().parent
_API_ROOT = _HERE.parent
_REPO_ROOT = _API_ROOT.parent
sys.path.insert(0, str(_API_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "runtime"))


# ---------------------------------------------------------------------------
# Spend tracking
# ---------------------------------------------------------------------------
# Conservative per-token pricing for Sonnet-4-6 / Opus-4-7. Anthropic's
# published list-price as of 2026:
#   Sonnet 4.6: $3 / 1M input, $15 / 1M output
#   Opus 4.7:   $15 / 1M input, $75 / 1M output
PRICING = {
    "claude-sonnet-4-6": {"in": 3.0 / 1_000_000, "out": 15.0 / 1_000_000},
    "claude-opus-4-7": {"in": 15.0 / 1_000_000, "out": 75.0 / 1_000_000},
}
SINGLE_RUN_CAP_USD = 3.0
TOTAL_CAP_USD = 5.0


def _model_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = PRICING.get(model)
    if p is None:
        # default to Opus pricing as a safe upper bound
        p = PRICING["claude-opus-4-7"]
    return input_tokens * p["in"] + output_tokens * p["out"]


# ---------------------------------------------------------------------------
# Synthetic PDF fixture
# ---------------------------------------------------------------------------
def make_concept_pdf() -> bytes:
    """Generate a 1-page concept site plan PDF using reportlab."""
    from io import BytesIO

    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER, leftMargin=54, rightMargin=54,
        topMargin=54, bottomMargin=54,
    )
    styles = getSampleStyleSheet()
    flow: list[Any] = []
    flow.append(Paragraph(
        "<b>QPB1 \u2014 Concept Site Plan (Class 5 Screening)</b>",
        styles["Title"],
    ))
    flow.append(Spacer(1, 12))
    flow.append(Paragraph(
        "Issue date: 2026-04-12 \u2014 For internal screening only. "
        "Hyperscale data center campus, 4 buildings + central energy plant, "
        "Central Ohio.",
        styles["Normal"],
    ))
    flow.append(Spacer(1, 12))
    flow.append(Paragraph("<b>Program summary</b>", styles["Heading2"]))
    bullets = [
        "Site: 220 acres greenfield, M-1 zoning, two highway frontage points.",
        "Total program: 4 data center buildings, ~450,000 SF each, total \u22481.8M SF.",
        "IT capacity target: 96 MW total (24 MW per building).",
        "Central energy plant: 4 chillers, dual MV substation feed.",
        "Stormwater: ~12 acres detention basin north of Building 4.",
        "Sub-grade: USCS-CL clay; estimated 2.5M CY mass earthwork.",
        "Substantial completion target: 2029-09-30.",
        "No structural, MEP, civil engineering sheets included in this issue.",
        "No equipment schedules, specifications, or vendor data.",
    ]
    for b in bullets:
        flow.append(Paragraph("\u2022 " + b, styles["Normal"]))
        flow.append(Spacer(1, 4))
    flow.append(Spacer(1, 12))
    flow.append(Paragraph("<b>Design maturity</b>", styles["Heading2"]))
    flow.append(Paragraph(
        "This is a concept screening package only. Massing diagrams and "
        "site context only. Estimate class supportable: Class 5 "
        "(\u221250% / +100%). To unlock Class 4 we need a sheet set "
        "with site plan + grading, gross floor plans, electrical one-line, "
        "mechanical block diagram, and a programmatic equipment list.",
        styles["Normal"],
    ))
    doc.build(flow)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Synthetic IFC fixture
# ---------------------------------------------------------------------------
def make_concept_ifc() -> bytes:
    """Generate a tiny IFC file with a few walls + a space + quantities.

    Uses the lower-level `ifcopenshell.file()` constructor + create_entity()
    so we don't depend on the high-level api wrappers (which have shifted
    signatures across releases). Minimal but valid IFC4.
    """
    import tempfile
    import uuid as _uuid

    import ifcopenshell  # type: ignore

    def _guid() -> str:
        # IFC GUID is a 22-char base64 form; ifcopenshell ships a util.
        try:
            from ifcopenshell.guid import compress  # type: ignore
            return compress(_uuid.uuid4().hex)
        except Exception:  # noqa: BLE001
            return _uuid.uuid4().hex[:22]

    model = ifcopenshell.file(schema="IFC4")

    # Owner history scaffolding (minimal)
    person = model.create_entity("IfcPerson", FamilyName="Quill")
    org = model.create_entity("IfcOrganization", Name="Quill")
    p_and_o = model.create_entity(
        "IfcPersonAndOrganization",
        ThePerson=person, TheOrganization=org,
    )
    app = model.create_entity(
        "IfcApplication", ApplicationDeveloper=org,
        Version="0.1", ApplicationFullName="Quill",
        ApplicationIdentifier="quill",
    )
    owner_history = model.create_entity(
        "IfcOwnerHistory",
        OwningUser=p_and_o, OwningApplication=app,
        ChangeAction="NOCHANGE", CreationDate=int(time.time()),
    )

    # Units
    length_unit = model.create_entity(
        "IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE",
    )
    area_unit = model.create_entity(
        "IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE",
    )
    volume_unit = model.create_entity(
        "IfcSIUnit", UnitType="VOLUMEUNIT", Name="CUBIC_METRE",
    )
    units = model.create_entity(
        "IfcUnitAssignment",
        Units=[length_unit, area_unit, volume_unit],
    )

    # Geometric context (required for IfcProject)
    origin = model.create_entity(
        "IfcCartesianPoint", Coordinates=[0.0, 0.0, 0.0]
    )
    placement_3d = model.create_entity(
        "IfcAxis2Placement3D", Location=origin
    )
    geom_ctx = model.create_entity(
        "IfcGeometricRepresentationContext",
        ContextIdentifier="Model", ContextType="Model",
        CoordinateSpaceDimension=3, Precision=1e-5,
        WorldCoordinateSystem=placement_3d,
    )

    project = model.create_entity(
        "IfcProject", GlobalId=_guid(), OwnerHistory=owner_history,
        Name="QPB1-DC1",
        RepresentationContexts=[geom_ctx], UnitsInContext=units,
    )
    site = model.create_entity(
        "IfcSite", GlobalId=_guid(), OwnerHistory=owner_history,
        Name="QPB1 Site", CompositionType="ELEMENT",
    )
    building = model.create_entity(
        "IfcBuilding", GlobalId=_guid(), OwnerHistory=owner_history,
        Name="DC1", CompositionType="ELEMENT",
    )
    storey = model.create_entity(
        "IfcBuildingStorey", GlobalId=_guid(), OwnerHistory=owner_history,
        Name="Ground Floor", CompositionType="ELEMENT",
    )
    # Aggregate hierarchy
    model.create_entity(
        "IfcRelAggregates", GlobalId=_guid(), OwnerHistory=owner_history,
        RelatingObject=project, RelatedObjects=[site],
    )
    model.create_entity(
        "IfcRelAggregates", GlobalId=_guid(), OwnerHistory=owner_history,
        RelatingObject=site, RelatedObjects=[building],
    )
    model.create_entity(
        "IfcRelAggregates", GlobalId=_guid(), OwnerHistory=owner_history,
        RelatingObject=building, RelatedObjects=[storey],
    )

    # Walls + a Space
    walls = []
    for i in range(4):
        w = model.create_entity(
            "IfcWall", GlobalId=_guid(), OwnerHistory=owner_history,
            Name=f"Exterior Wall {i+1}",
        )
        walls.append(w)
    space = model.create_entity(
        "IfcSpace", GlobalId=_guid(), OwnerHistory=owner_history,
        Name="Data Hall A", CompositionType="ELEMENT",
    )
    # Contain walls + space in storey
    model.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=_guid(), OwnerHistory=owner_history,
        RelatedElements=walls + [space],
        RelatingStructure=storey,
    )

    # Quantities for the data-hall space
    qspace_area = model.create_entity(
        "IfcQuantityArea", Name="GrossFloorArea",
        AreaValue=5000.0, Unit=area_unit,
    )
    qspace_net = model.create_entity(
        "IfcQuantityArea", Name="NetFloorArea",
        AreaValue=4500.0, Unit=area_unit,
    )
    qspace_vol = model.create_entity(
        "IfcQuantityVolume", Name="GrossVolume",
        VolumeValue=75000.0, Unit=volume_unit,
    )
    space_qto = model.create_entity(
        "IfcElementQuantity", GlobalId=_guid(), OwnerHistory=owner_history,
        Name="Qto_SpaceBaseQuantities",
        Quantities=[qspace_area, qspace_net, qspace_vol],
    )
    model.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=_guid(), OwnerHistory=owner_history,
        RelatingPropertyDefinition=space_qto, RelatedObjects=[space],
    )

    # Quantities per wall
    for i, wall in enumerate(walls):
        length_m = 100.0 + i * 10.0
        height_m = 9.0
        side_area = length_m * height_m
        net_vol = side_area * 0.3
        q_len = model.create_entity(
            "IfcQuantityLength", Name="Length",
            LengthValue=length_m, Unit=length_unit,
        )
        q_h = model.create_entity(
            "IfcQuantityLength", Name="Height",
            LengthValue=height_m, Unit=length_unit,
        )
        q_a = model.create_entity(
            "IfcQuantityArea", Name="GrossSideArea",
            AreaValue=side_area, Unit=area_unit,
        )
        q_v = model.create_entity(
            "IfcQuantityVolume", Name="NetVolume",
            VolumeValue=net_vol, Unit=volume_unit,
        )
        wq = model.create_entity(
            "IfcElementQuantity",
            GlobalId=_guid(), OwnerHistory=owner_history,
            Name="Qto_WallBaseQuantities",
            Quantities=[q_len, q_h, q_a, q_v],
        )
        model.create_entity(
            "IfcRelDefinesByProperties",
            GlobalId=_guid(), OwnerHistory=owner_history,
            RelatingPropertyDefinition=wq, RelatedObjects=[wall],
        )

    with tempfile.NamedTemporaryFile(suffix=".ifc", delete=False) as tmp:
        tmp.close()
        model.write(tmp.name)
        data = Path(tmp.name).read_bytes()
        os.unlink(tmp.name)
    return data


# ---------------------------------------------------------------------------
# Drawing extraction (in-process)
# ---------------------------------------------------------------------------
def extract_files(pdf_bytes: bytes, ifc_bytes: bytes) -> list[dict[str, Any]]:
    """Run both files through the extraction pipeline and return a manifest."""
    from app.services.drawings import extract  # type: ignore

    pdf_result = extract(filename="QPB1-Concept-Site-Plan.pdf", data=pdf_bytes)
    ifc_result = extract(filename="QPB1-DC1-Concept.ifc", data=ifc_bytes)

    print(f"\n[extract] PDF:  status={pdf_result.extraction_status}  "
          f"summary={pdf_result.summary[:140]}")
    print(f"[extract] IFC:  status={ifc_result.extraction_status}  "
          f"summary={ifc_result.summary[:140]}")
    return [pdf_result, ifc_result]


# ---------------------------------------------------------------------------
# Build agent inputs
# ---------------------------------------------------------------------------
# Re-exported from the shared module so the smoke script keeps its original
# call-site (build_classifier_input(extraction_results)) while the
# classification dispatcher also uses the exact same code path.
from app.services.classifier_input import build_classifier_input as _build_classifier_input  # noqa: E402


def build_classifier_input(extraction_results: list[Any]) -> dict[str, Any]:
    """Shape input per design-classifier examples.

    Delegates to the shared ``app.services.classifier_input`` module so that
    both the smoke script and the classification dispatcher use identical
    input-building logic.  The output shape is unchanged.
    """
    return _build_classifier_input(
        extraction_results,
        project_label="QPB1 \u2014 Smoke test concept site",
        notes="Synthetic concept screening package generated by the G.4 smoke test.",
        context={
            "project_type": "hyperscale_data_center",
            "approximate_size_sf": 1_800_000,
            "approximate_capacity_mw": 96,
            "geographic_basis": "Central Ohio, USA",
        },
    )


def build_estimator_input(
    extraction_results: list[Any], classification_artifact: dict[str, Any]
) -> dict[str, Any]:
    """Shape input per estimator-scheduler examples."""
    pdf_extracts = []
    ifc_extracts = []
    for r in extraction_results:
        if r.kind == "pdf":
            pdf_extracts.append({
                "filename": r.filename,
                "page_count": r.entities.get("page_count", 0),
                "extracted_text_excerpts": r.entities.get(
                    "text_excerpts", []
                )[:5],
            })
        elif r.kind == "ifc":
            ifc_extracts.append({
                "filename": r.filename,
                "entities": r.entities,
                "quantities": r.quantities,
            })

    meta = classification_artifact.get("metadata") or {}
    return {
        "project_label": "QPB1 \u2014 Smoke test concept site",
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
            ) or [],
            "missing_for_next_class": meta.get("missing_for_next_class") or [],
        },
        "extracted_scope": {
            "pdf": pdf_extracts,
            "ifc": ifc_extracts,
        },
        "cost_library": {
            "version": "v0.1.0-smoke",
            "currency": "USD",
            "base_year": "2026",
            "rows": [
                {"csi_section": "01 00 00", "description": "ROM hyperscale-DC build",
                 "unit": "MW", "unit_rate_usd": 11_500_000, "rate_source": "llm_estimate",
                 "rate_year": 2026, "geographic_multiplier_for": "Central Ohio",
                 "confidence": 0.45},
                {"csi_section": "31 00 00", "description": "Sitework / earthwork ROM",
                 "unit": "CY", "unit_rate_usd": 12.5, "rate_source": "llm_estimate",
                 "rate_year": 2026, "confidence": 0.45},
                {"csi_section": "26 13 13", "description": "MV switchgear, 15kV",
                 "unit": "EA", "unit_rate_usd": 285_000, "rate_source": "llm_estimate",
                 "rate_year": 2026, "confidence": 0.5},
            ],
        },
        "project_context": {
            "project_type": "hyperscale_data_center",
            "approximate_size_sf": 1_800_000,
            "approximate_capacity_mw": 96,
            "geographic_basis": "Central Ohio, USA",
            "target_substantial_completion_date": "2029-09-30",
            "shifts": "5x10",
            "weather_calendar": "Central Ohio standard",
        },
    }


# ---------------------------------------------------------------------------
# Run a single agent against the live Anthropic API
# ---------------------------------------------------------------------------
async def run_agent_live(
    agent_id: str,
    input_payload: dict[str, Any],
    *,
    cumulative_cost: float,
) -> tuple[Any, float]:
    """Execute the agent against live Anthropic. Returns (AgentRun, cost_usd).

    Aborts (raises RuntimeError) if cost exceeds SINGLE_RUN_CAP_USD or if
    the cumulative budget would be exceeded.
    """
    # Lazy imports so this script doesn't hard-depend on runtime when used
    # for fixture generation only.
    from runtime.agent import Agent  # type: ignore
    from runtime.config import get_config  # type: ignore

    cfg = get_config()
    if not cfg.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set; cannot run live smoke test"
        )

    print(f"\n[agent.{agent_id}] dispatching live LLM call...")
    t0 = time.time()
    agent = Agent(agent_id, config=cfg)
    run = await agent.run(input_payload, submit_to_queue=False, prompt_cache=False)
    elapsed = time.time() - t0

    cost = _model_cost(
        run.model_used,
        run.tokens_used.get("input", 0),
        run.tokens_used.get("output", 0),
    )
    print(
        f"[agent.{agent_id}] done in {elapsed:.1f}s "
        f"model={run.model_used} "
        f"in={run.tokens_used.get('input', 0)} "
        f"out={run.tokens_used.get('output', 0)} "
        f"validation_ok={run.validation_ok} "
        f"cost~=${cost:.3f}"
    )
    if run.error:
        print(f"[agent.{agent_id}] error: {run.error}")
    if cost > SINGLE_RUN_CAP_USD:
        raise RuntimeError(
            f"single-run cost ${cost:.2f} exceeded cap ${SINGLE_RUN_CAP_USD:.2f}"
        )
    if cumulative_cost + cost > TOTAL_CAP_USD:
        raise RuntimeError(
            f"cumulative cost ${cumulative_cost + cost:.2f} would exceed "
            f"cap ${TOTAL_CAP_USD:.2f}"
        )
    return run, cost


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main_async() -> int:
    print("=" * 78)
    print(" Phase G.4 \u2014 End-to-end smoke test (LIVE Anthropic API)")
    print("=" * 78)

    # Load .env from repo root if present
    try:
        from dotenv import load_dotenv

        load_dotenv(_REPO_ROOT / ".env")
    except Exception:  # noqa: BLE001
        pass
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nERROR: ANTHROPIC_API_KEY not set. Source .env and re-run.")
        return 2

    # Output dir
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    out_dir = _HERE / "smoke_results" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n[output] {out_dir}")

    # 1. Build fixtures
    print("\n[1/5] Building synthetic fixtures...")
    pdf_bytes = make_concept_pdf()
    ifc_bytes = make_concept_ifc()
    (out_dir / "fixture.pdf").write_bytes(pdf_bytes)
    (out_dir / "fixture.ifc").write_bytes(ifc_bytes)
    print(f"  PDF: {len(pdf_bytes)} bytes")
    print(f"  IFC: {len(ifc_bytes)} bytes")

    # 2. Extract
    print("\n[2/5] Running drawing extraction...")
    extraction_results = extract_files(pdf_bytes, ifc_bytes)

    # 3. Run design-classifier
    print("\n[3/5] Running design-classifier (LIVE)...")
    classifier_input = build_classifier_input(extraction_results)
    (out_dir / "01_classifier_input.json").write_text(
        json.dumps(classifier_input, indent=2, default=str), encoding="utf-8"
    )

    cumulative = 0.0
    try:
        cls_run, cls_cost = await run_agent_live(
            "design-classifier", classifier_input,
            cumulative_cost=cumulative,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"\nFATAL classifier: {exc}")
        return 3
    cumulative += cls_cost

    cls_output = cls_run.output or {}
    (out_dir / "02_classifier_output.json").write_text(
        json.dumps(cls_output, indent=2, default=str), encoding="utf-8"
    )

    # Pretty-print the classification key fields
    cls_meta = cls_output.get("metadata") or {}
    print("\n--- design-classifier verbatim summary ---")
    print(f"  class                 = {cls_meta.get('class')}")
    print(f"  confidence            = {cls_output.get('confidence')}")
    print(f"  design_maturity_pct   = {cls_meta.get('design_maturity_estimate_pct')}")
    missing = cls_meta.get("missing_for_next_class") or []
    print(f"  missing_for_next_class ({len(missing)}):")
    for m in missing[:5]:
        print(f"    - {m.get('deliverable')} (would unlock Class {m.get('would_unlock_class')})")
    print(f"  validation_ok         = {cls_run.validation_ok}")
    if cls_run.validation_errors:
        print(f"  validation_errors     = {cls_run.validation_errors[:3]}")

    # 4. Auto-approve classification (smoke-test only) and run estimator-scheduler
    print("\n[4/5] Auto-approving classification (smoke-only) and running estimator-scheduler (LIVE)...")
    estimator_input = build_estimator_input(extraction_results, cls_output)
    (out_dir / "03_estimator_input.json").write_text(
        json.dumps(estimator_input, indent=2, default=str), encoding="utf-8"
    )
    try:
        est_run, est_cost = await run_agent_live(
            "estimator-scheduler", estimator_input,
            cumulative_cost=cumulative,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"\nFATAL estimator: {exc}")
        return 4
    cumulative += est_cost

    est_output = est_run.output or {}
    (out_dir / "04_estimator_output.json").write_text(
        json.dumps(est_output, indent=2, default=str), encoding="utf-8"
    )

    # 5. Pretty-print results
    print("\n[5/5] Verifying + printing summary...")
    em = est_output.get("metadata") or {}
    estimate = em.get("estimate") or {}
    rows = (estimate.get("rows") or [])[:5]
    print("\n--- estimator-scheduler verbatim summary ---")
    print(f"  total_usd            = {estimate.get('total_usd')}")
    print(f"  total_per_sf_usd     = {estimate.get('total_per_sf_usd')}")
    print(f"  total_per_mw_usd     = {estimate.get('total_per_mw_usd')}")
    print(f"  subtotal_direct_usd  = {estimate.get('subtotal_direct_usd')}")
    schedule = em.get("schedule") or {}
    activities = (schedule.get("activities") or [])
    print(f"  total_duration_days  = {schedule.get('total_duration_days')}")
    print(f"  activities count     = {len(activities)}")
    print(f"  validation_ok        = {est_run.validation_ok}")
    if est_run.validation_errors:
        print(f"  validation_errors    = {est_run.validation_errors[:3]}")

    print(f"\n  Top {len(rows)} cost-code rows:")
    for r in rows:
        print(
            f"    {r.get('csi_section')}  {r.get('description', '')[:60]:60s}  "
            f"{r.get('quantity')} {r.get('unit')} @ ${r.get('unit_rate_usd')}/u "
            f"= ${r.get('extended_usd')}"
        )

    print(f"\n  Top 5 schedule activities:")
    for a in activities[:5]:
        print(
            f"    {a.get('id', '')[:8]:8s}  {a.get('name', '')[:48]:48s}  "
            f"WBS={a.get('wbs', '')}  {a.get('duration_days')}d"
        )

    # Write summary
    summary = {
        "stamp_utc": stamp,
        "cumulative_cost_usd": round(cumulative, 4),
        "classifier": {
            "model": cls_run.model_used,
            "input_tokens": cls_run.tokens_used.get("input", 0),
            "output_tokens": cls_run.tokens_used.get("output", 0),
            "cost_usd": round(cls_cost, 4),
            "validation_ok": cls_run.validation_ok,
            "class": cls_meta.get("class"),
            "confidence": cls_output.get("confidence"),
            "missing_for_next_class": missing,
        },
        "estimator": {
            "model": est_run.model_used,
            "input_tokens": est_run.tokens_used.get("input", 0),
            "output_tokens": est_run.tokens_used.get("output", 0),
            "cost_usd": round(est_cost, 4),
            "validation_ok": est_run.validation_ok,
            "total_usd": estimate.get("total_usd"),
            "total_per_sf_usd": estimate.get("total_per_sf_usd"),
            "total_per_mw_usd": estimate.get("total_per_mw_usd"),
            "total_duration_days": schedule.get("total_duration_days"),
            "top_5_rows": rows,
            "top_5_activities": activities[:5],
        },
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )

    print(f"\nTotal cost: ${cumulative:.3f}")
    print(f"Smoke results: {out_dir}")
    print("\nDONE.")
    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
