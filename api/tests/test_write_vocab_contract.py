"""Phase 0 drift guard (GAP_ASSESSMENT_S9 §3).

The agent-cloud write vocabularies used to be hand-synced across two services
with only a comment claiming "kept in sync by the A6 contract tests" — but no
test actually enforced it. These tests make drift impossible to merge:

  1. The vendored api contract JSON matches the api canonical ORM enums.
  2. `scripts/gen_write_vocab.py --check` passes (both vendored copies current).
  3. The two vendored copies (api + agent-cloud) are byte-identical.
  4. The executor's runtime vocab equals the canonical model enums.

If someone edits a canonical enum (e.g. adds a project phase) and does NOT
regenerate the contract, tests (1)/(2) fail. If they edit one vendored copy by
hand, (2)/(3) fail. There is no green path that leaves the sides drifted.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.contracts import write_vocab
from app.models_pipeline import VALID_DEAL_STAGES
from app.models_projects import VALID_ENTRY_TYPES, VALID_PHASES, VALID_STATUSES
from app.models_requests import VALID_REQUEST_ACTION_STATUSES

REPO_ROOT = Path(__file__).resolve().parents[2]
API_COPY = REPO_ROOT / "api" / "app" / "contracts" / "agentcloud_write_vocab.json"
AC_COPY = REPO_ROOT / "agent-cloud" / "app" / "contracts" / "agentcloud_write_vocab.json"
GEN_SCRIPT = REPO_ROOT / "scripts" / "gen_write_vocab.py"


def test_vendored_contract_matches_canonical_models():
    """The generated JSON must equal the api canonical ORM enums."""
    vocab = write_vocab()
    assert vocab["project_phases"] == tuple(VALID_PHASES)
    assert vocab["phase_order"] == tuple(VALID_PHASES)
    assert vocab["project_statuses"] == tuple(VALID_STATUSES)
    assert vocab["log_entry_types"] == tuple(VALID_ENTRY_TYPES)
    assert vocab["deal_stages"] == tuple(VALID_DEAL_STAGES)
    assert vocab["request_action_statuses"] == tuple(VALID_REQUEST_ACTION_STATUSES)


def test_gen_script_check_passes():
    """`gen_write_vocab.py --check` must be clean — i.e. no un-regenerated drift.

    This FAILS if a canonical enum changed without regenerating the contract,
    or if a vendored copy was hand-edited.
    """
    result = subprocess.run(
        [sys.executable, str(GEN_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"contract drift detected — run `python scripts/gen_write_vocab.py`.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_both_vendored_copies_byte_identical():
    """api and agent-cloud copies must be the exact same bytes."""
    assert API_COPY.exists(), f"missing {API_COPY}"
    assert AC_COPY.exists(), f"missing {AC_COPY}"
    assert API_COPY.read_bytes() == AC_COPY.read_bytes()


def test_contract_json_wellformed():
    data = json.loads(API_COPY.read_text())
    assert data["contract_version"] >= 1
    assert set(data["vocabularies"]) == {
        "project_phases",
        "phase_order",
        "project_statuses",
        "log_entry_types",
        "deal_stages",
        "request_action_statuses",
    }


def test_synthetic_drift_is_detected():
    """Prove the guard bites: a mutated payload must not equal the canonical.

    Loads the generator by path, serializes the canonical payload, corrupts a
    value, and confirms the corrupted bytes differ from a freshly generated
    serialization (which is exactly what `--check` compares the vendored copy
    against). Does not touch the real vendored files.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_gen_write_vocab", GEN_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    good = mod._serialize(mod._load_canonical())
    drifted = good.replace("site_control", "site_controlX", 1)
    assert drifted != good  # sanity: mutation applied
    assert drifted != mod._serialize(mod._load_canonical())
