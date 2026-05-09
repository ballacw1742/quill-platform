#!/usr/bin/env python3
"""Bootstrap the cost_library_rows table from a JSON library file.

Default source: ../agentic-pmo-prompts/data/cost_library_v0_1.json
Default target: the configured DATABASE_URL_SYNC.

Usage:
    python api/scripts/bootstrap_cost_library.py [--src PATH] [--replace]

If --replace is passed, all existing rows for the file's `version` are
deleted first. Otherwise the loader is upsert-style (skip existing).

The schema validation step verifies the file matches
agentic-pmo-prompts/schemas/cost_library.schema.json before touching
the DB. Validation is best-effort: if jsonschema is unavailable or the
schema can't be located the script logs a warning and continues.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

# Allow running from anywhere; resolve api/ on sys.path for app.* imports.
HERE = Path(__file__).resolve().parent
API_DIR = HERE.parent
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

# Default library path: walk up from api/ to workspace root, then sideways to
# agentic-pmo-prompts/data.
DEFAULT_SRC = (
    Path(__file__).resolve().parents[2].parent
    / "agentic-pmo-prompts"
    / "data"
    / "cost_library_v0_1.json"
)
DEFAULT_SCHEMA = (
    Path(__file__).resolve().parents[2].parent
    / "agentic-pmo-prompts"
    / "schemas"
    / "cost_library.schema.json"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bootstrap_cost_library")


def _validate(data: dict[str, Any], schema_path: Path) -> None:
    if not schema_path.exists():
        log.warning("schema not found at %s; skipping validation", schema_path)
        return
    try:
        from jsonschema import Draft202012Validator  # type: ignore
    except ImportError:
        log.warning("jsonschema not installed; skipping validation")
        return
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    errs = list(Draft202012Validator(schema).iter_errors(data))
    if errs:
        for e in errs[:10]:
            log.error("schema fail %s: %s", list(e.absolute_path), e.message)
        raise SystemExit(2)
    log.info("library validates OK against cost_library.schema.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    ap.add_argument(
        "--replace",
        action="store_true",
        help="Delete all rows for this version before inserting.",
    )
    args = ap.parse_args()

    src = Path(args.src)
    if not src.exists():
        log.error("source library not found: %s", src)
        return 2
    data = json.loads(src.read_text())
    _validate(data, Path(args.schema))

    version = str(data["version"])
    rows = list(data.get("rows") or [])
    log.info("loading %d rows for library version %s from %s", len(rows), version, src)

    # Late imports so the script can validate even without DB env set up.
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./quill_dev.db")
    os.environ.setdefault("DATABASE_URL_SYNC", "sqlite:///./quill_dev.db")
    os.environ.setdefault("SECRET_KEY", "bootstrap-secret")
    os.environ.setdefault("AGENT_SHARED_SECRET", "bootstrap-agent")
    os.environ.setdefault("CORS_ORIGINS", "http://localhost")
    os.environ.setdefault("WEBAUTHN_RP_ID", "localhost")
    os.environ.setdefault("WEBAUTHN_RP_NAME", "Quill")
    os.environ.setdefault("WEBAUTHN_ORIGIN", "http://localhost:3000")
    os.environ.setdefault("ACTION_ASSERTION_SECRET", "bootstrap-action")

    from sqlalchemy import create_engine, delete, select
    from sqlalchemy.orm import sessionmaker

    from app.config import get_settings
    from app.models import CostLibraryRow

    settings = get_settings()
    engine = create_engine(
        settings.DATABASE_URL_SYNC, future=True, echo=False
    )
    SyncSession = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    inserted = 0
    skipped = 0
    with SyncSession() as s:
        if args.replace:
            n = s.execute(
                delete(CostLibraryRow).where(CostLibraryRow.library_version == version)
            ).rowcount or 0
            log.info("--replace removed %d existing rows for version %s", n, version)

        # Build a fast (csi, desc) set of the existing rows for this version.
        existing = {
            (r.csi_section, r.description)
            for r in s.execute(
                select(CostLibraryRow).where(
                    CostLibraryRow.library_version == version
                )
            ).scalars().all()
        }

        for row in rows:
            key = (row["csi_section"], row["description"])
            if key in existing:
                skipped += 1
                continue
            s.add(
                CostLibraryRow(
                    id=str(uuid.uuid4()),
                    library_version=version,
                    csi_section=row["csi_section"],
                    description=row["description"],
                    unit=row["unit"],
                    unit_rate_usd=float(row["unit_rate_usd"]),
                    rate_source=row["rate_source"],
                    rate_year=int(row["rate_year"]),
                    geographic_multiplier_for=row.get("geographic_multiplier_for"),
                    confidence=float(row.get("confidence", 0.5)),
                    notes=row.get("notes"),
                    tags=row.get("tags") or [],
                )
            )
            inserted += 1
        s.commit()

    log.info("done: inserted=%d skipped=%d (already present)", inserted, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
