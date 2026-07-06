"""Campus template engine — Sprint 5.4 (48-hour campus deployment).

Loads the data-driven template catalog from ``campus_templates.json`` and
resolves a (campus_type, jurisdiction, region) triple into the concrete
artifact lists the deploy workflow creates:

  * equipment list (per campus type)
  * monitoring agents (per campus type)
  * ops dashboard seed metrics (per campus type)
  * compliance checklist (per jurisdiction, falls back to ``default``)
  * vendor contact list (per region, falls back to ``default``)

Templates are data, not code — edit the JSON to change what a deployment
creates. Route handlers must not hardcode artifact lists.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger("quill.campus_templates")

TEMPLATE_PATH = Path(__file__).with_name("campus_templates.json")


class TemplateResolutionError(ValueError):
    """Raised when a requested template key cannot be resolved."""


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    """Load and cache the template catalog JSON."""
    with TEMPLATE_PATH.open(encoding="utf-8") as f:
        catalog = json.load(f)
    for key in ("campus_types", "jurisdictions", "regions"):
        if key not in catalog or not isinstance(catalog[key], dict):
            raise TemplateResolutionError(f"template catalog missing section: {key}")
    return catalog


def catalog_summary() -> dict[str, list[dict[str, str]]]:
    """Compact catalog listing for UI dropdowns (GET /v1/campuses/deploy-templates)."""
    catalog = load_catalog()
    return {
        "campus_types": [
            {"key": k, "label": v.get("label", k)}
            for k, v in catalog["campus_types"].items()
        ],
        "jurisdictions": [
            {"key": k, "label": v.get("label", k)}
            for k, v in catalog["jurisdictions"].items()
        ],
        "regions": [
            {"key": k, "label": v.get("label", k)}
            for k, v in catalog["regions"].items()
        ],
    }


def resolve_template(
    campus_type: str,
    jurisdiction: str,
    region: str,
) -> dict[str, Any]:
    """Resolve template keys into concrete artifact definitions.

    ``campus_type`` must exist. ``jurisdiction`` and ``region`` fall back to
    the ``default`` entry (recorded in the returned dict so the deployment
    report can surface the fallback).
    """
    catalog = load_catalog()

    ct = catalog["campus_types"].get(campus_type)
    if ct is None:
        valid = ", ".join(sorted(catalog["campus_types"]))
        raise TemplateResolutionError(
            f"unknown campus_type '{campus_type}' — valid types: {valid}"
        )

    jur_used = jurisdiction if jurisdiction in catalog["jurisdictions"] else "default"
    reg_used = region if region in catalog["regions"] else "default"
    if jur_used != jurisdiction:
        log.info("campus_template.jurisdiction_fallback requested=%s used=default", jurisdiction)
    if reg_used != region:
        log.info("campus_template.region_fallback requested=%s used=default", region)

    return {
        "campus_type": campus_type,
        "jurisdiction_requested": jurisdiction,
        "jurisdiction_used": jur_used,
        "region_requested": region,
        "region_used": reg_used,
        "campus": ct,
        "compliance": catalog["jurisdictions"][jur_used],
        "vendors": catalog["regions"][reg_used]["vendors"],
    }
