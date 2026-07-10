"""Deliverable Registry — Phase B (deliverable producer).

A declarative mapping from ``deliverable_type`` → registry entry that drives
automatic deliverable production when an agent completes a piloted intent.

Design rules (from MODULAR_FRAMEWORK_DESIGN.md Part B):
  - Keyed by ``deliverable_type`` (the canonical string stored on the
    Deliverable row and used for filtering/display).
  - Each entry records which ``module_key`` owns it and which ``intent``
    produces it so the producer in routes/requests.py can do a single
    INTENT_TO_DELIVERABLE lookup.
  - ``title_template`` is a Python format string; callers pass ``message``
    (the first ~60 chars of the request message) as the only substitution.
  - Adding a new piloted type = one new entry here. Nothing else needs changing.

Phase B seeds exactly two pilots:

  cost_estimate   estimates module  ←  intent "estimate"
  rfi_response    projects module   ←  intent "rfi"
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeliverableRegistryEntry:
    """Describes one deliverable type that the system can auto-produce."""

    module_key: str
    """Module that owns this deliverable (must match INTENT_TO_MODULE)."""

    deliverable_type: str
    """Canonical type string stored on the Deliverable row."""

    produced_by_intent: str
    """The request intent that triggers production of this deliverable type."""

    title_template: str
    """
    Python format string used to build the deliverable title.
    Available substitution key: ``{message}`` (first ~60 chars of the
    request message, stripped).
    """


# ---------------------------------------------------------------------------
# Registry — seed for Phase B (two pilots).
# ---------------------------------------------------------------------------
# ``deliverable_type`` is the key so callers can look up by type as well as
# by intent (via the ``INTENT_TO_DELIVERABLE`` helper below).
# ---------------------------------------------------------------------------

DELIVERABLE_REGISTRY: dict[str, DeliverableRegistryEntry] = {
    "cost_estimate": DeliverableRegistryEntry(
        module_key="estimates",
        deliverable_type="cost_estimate",
        produced_by_intent="estimate",
        title_template="Cost estimate — {message}",
    ),
    "rfi_response": DeliverableRegistryEntry(
        module_key="projects",
        deliverable_type="rfi_response",
        produced_by_intent="rfi",
        title_template="RFI response — {message}",
    ),
}

# Convenience reverse-index: intent → registry entry (only piloted intents).
INTENT_TO_DELIVERABLE: dict[str, DeliverableRegistryEntry] = {
    entry.produced_by_intent: entry
    for entry in DELIVERABLE_REGISTRY.values()
}
