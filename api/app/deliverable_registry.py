"""Deliverable Registry — Phase C (deliverable pipeline orchestrator).

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

Phase C extends each entry with an ordered ``steps: list[ChainStep]`` that
defines the multi-step agent chain. Step A's output becomes Step B's input
context, building on prior work — never destructive.

ChainStep fields:
  key           — short slug recorded in deliverable.meta for lineage tracing
  agent_name    — ADK agent name (same pool as INTENT_TO_ADK_AGENT)
  prompt_suffix — text appended to the seed_message to form this step's prompt.
                  Step B+ also receive the prior step's output as context.
  role          — human-readable label for logging/display

The two-step chains below are the Phase C pilots. Phase D will add a third
"awaiting_human" gate step for each type. Keep the structure declarative and
extensible — adding a new step is a one-line change here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChainStep:
    """One step in a deliverable production chain."""

    key: str
    """Short slug stored in deliverable.meta for lineage (e.g. 'scope_draft')."""

    agent_name: str
    """ADK agent name for POST /invoke (same pool as INTENT_TO_ADK_AGENT)."""

    prompt_suffix: str
    """
    Appended to the seed message to form this step's prompt.

    For step A (index 0) the full prompt is: ``{seed_message}\\n\\n{prompt_suffix}``
    For subsequent steps the prior step's output is prepended as context:
      ``Prior step output:\\n{prior_output}\\n\\n{seed_message}\\n\\n{prompt_suffix}``

    Use an empty string if the suffix adds nothing beyond the seed message.
    """

    role: str = ""
    """Human-readable label for logging and display (e.g. 'Scope/Takeoff Draft')."""


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

    steps: list[ChainStep] = field(default_factory=list)
    """
    Ordered chain steps for Phase C orchestration.

    If ``steps`` is empty, the pipeline falls back to the Phase B
    single-shot create (legacy path — safe for non-piloted types).
    If ``steps`` has one entry, only Step A runs (same as Phase B but
    structured). Two or more entries run the full chain.

    The first step (index 0) creates v1; each subsequent step appends
    a new version to the same Deliverable row, building on prior output.
    """


# ---------------------------------------------------------------------------
# Registry — seed for Phase C (two pilots with 2-step chains each).
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
        steps=[
            ChainStep(
                key="scope_draft",
                agent_name="quill_coordinator",
                prompt_suffix=(
                    "You are performing Step A (Scope & Takeoff Draft) of a cost estimate. "
                    "Analyze the request, identify all line items, quantities, and work "
                    "breakdown structure. Produce a structured scope/takeoff draft."
                ),
                role="Scope/Takeoff Draft",
            ),
            ChainStep(
                key="unit_pricing",
                agent_name="quill_coordinator",
                prompt_suffix=(
                    "You are performing Step B (Unit Pricing & Rough Order of Magnitude) of a "
                    "cost estimate. Using the scope/takeoff draft from the prior step as your "
                    "input, apply unit pricing to each line item and produce a rough order of "
                    "magnitude (ROM) cost estimate. Include a cost summary table."
                ),
                role="Unit Pricing / ROM Estimate",
            ),
            # Step C would be 'accept estimate' human gate — Phase D
        ],
    ),
    "rfi_response": DeliverableRegistryEntry(
        module_key="projects",
        deliverable_type="rfi_response",
        produced_by_intent="rfi",
        title_template="RFI response — {message}",
        steps=[
            ChainStep(
                key="rfi_intake",
                agent_name="quill_rfi_triage",
                prompt_suffix=(
                    "You are performing Step A (RFI Intake & Triage) of an RFI response. "
                    "Review the RFI request, identify the question or clarification needed, "
                    "classify its urgency and impact, and produce a structured intake/triage "
                    "summary with recommended response approach."
                ),
                role="RFI Intake/Triage Draft",
            ),
            ChainStep(
                key="rfi_draft",
                agent_name="quill_rfi_triage",
                prompt_suffix=(
                    "You are performing Step B (Drafted RFI Response) of an RFI response. "
                    "Using the intake/triage summary from the prior step as your context, "
                    "draft a complete, professional RFI response addressing all questions "
                    "raised. Include any clarifying assumptions and recommended next steps."
                ),
                role="Drafted RFI Response",
            ),
            # Step C would be 'approve RFI response' human gate — Phase D
        ],
    ),
}

# Convenience reverse-index: intent → registry entry (only piloted intents).
INTENT_TO_DELIVERABLE: dict[str, DeliverableRegistryEntry] = {
    entry.produced_by_intent: entry
    for entry in DELIVERABLE_REGISTRY.values()
}
