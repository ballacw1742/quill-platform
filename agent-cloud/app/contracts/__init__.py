"""Shared, generated contracts vendored into the agent-cloud service tree.

Phase 0 (GAP_ASSESSMENT_S9 §3): the write vocabularies used by the approval
proposal path used to be re-declared here by hand ("kept in sync by the A6
contract tests"). They are now generated from the api canonical ORM models by
`scripts/gen_write_vocab.py` into `agentcloud_write_vocab.json` — a
byte-identical copy vendored on each side, because agent-cloud and api build
from separate Docker contexts and cannot import each other's Python at runtime.

`write_vocab()` loads that JSON so `app.approvals` never redefines a vocabulary.
`tests/test_write_vocab_contract.py` fails the build if this vendored copy
drifts from the api canonical models.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_VOCAB_PATH = Path(__file__).with_name("agentcloud_write_vocab.json")


@lru_cache(maxsize=1)
def _load() -> dict:
    with _VOCAB_PATH.open() as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def write_vocab() -> dict[str, tuple[str, ...]]:
    """Return the shared write vocabularies as tuples (immutable, ordered).

    Keys: project_phases, phase_order, project_statuses, log_entry_types,
    deal_stages, request_action_statuses.
    """
    vocab = _load()["vocabularies"]
    return {k: tuple(v) for k, v in vocab.items()}


def contract_version() -> int:
    return int(_load()["contract_version"])
