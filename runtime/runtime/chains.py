"""Agent chains — declarative sequences of agents fed by an event.

A `Chain` declares an ordered list of agents to run for a given event class.
The output of agent N is folded into the input of agent N+1 via a small
templating helper (`_compose_inputs`). The combined chain output is what
the dispatcher submits to the Approval Queue, in a single combined item
whose `proposed_action.payload` includes a `chain_outputs` field.

This file is intentionally thin: it does NOT decide *whether* a chain runs
(that's TriageDispatcher's job); it only knows how to run one once
selected. Confidence-gating between chain steps is handled here via the
optional `Step.gate` callable.

Schema of `chain_outputs` (what the UI renders):

    {
        "chain_id": "rfi.full_triage",
        "steps": [
            {
                "agent_id": "rfi-triage",
                "ok": true,
                "confidence": 0.84,
                "output": { ... },           # full agent output
                "approval_id": null,         # only set if individual step submitted
                "model": "claude-opus-4-7",
                "latency_ms": 1840,
            },
            {
                "agent_id": "rfi-drafter",
                "ok": true,
                "confidence": 0.91,
                "output": { ... },
                ...
            }
        ],
        "skipped": [],         # agent_ids that were gated out
        "errors": []           # per-step error strings
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

from runtime.agent import Agent, AgentRun
from runtime.config import Config, get_config
from runtime.queue_client import QueueClient

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Step + Chain dataclasses
# ---------------------------------------------------------------------------
GateFn = Callable[[AgentRun, "ChainContext"], bool]
ComposerFn = Callable[[dict[str, Any], dict[str, Any], "ChainContext"], dict[str, Any]]


@dataclass(frozen=True)
class Step:
    """One agent in a chain.

    `gate` returns True if the next step *after* this one should run. The
    final step's gate is irrelevant. By default every step keeps the chain
    going.

    `compose_inputs` produces the input payload for THIS step from the
    original event payload + the running chain context (prior outputs).
    Default = pass through the original event payload + add a `prior`
    object with the previous step's output.
    """

    agent_id: str
    gate: GateFn | None = None
    compose_inputs: ComposerFn | None = None


@dataclass(frozen=True)
class Chain:
    """A named sequence of `Step`s for a given event class."""

    chain_id: str
    event_kinds: tuple[str, ...]
    steps: tuple[Step, ...]


@dataclass
class ChainContext:
    """Mutable state carried through a chain run."""

    event: dict[str, Any]
    chain: Chain
    runs: list[AgentRun] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ChainResult:
    chain_id: str
    runs: list[AgentRun]
    skipped: list[str]
    errors: list[str]
    submitted_approval_id: str | None = None
    submitted_payload: dict[str, Any] | None = None

    def to_chain_outputs(self) -> dict[str, Any]:
        """Render the structured `chain_outputs` blob the UI consumes."""
        return {
            "chain_id": self.chain_id,
            "steps": [
                {
                    "agent_id": r.agent_id,
                    "agent_version": r.agent_version,
                    "ok": r.validation_ok and r.error is None,
                    "confidence": (
                        r.lane_decision.confidence
                        if r.lane_decision is not None
                        else r.output.get("confidence") if r.output else None
                    ),
                    "output": r.output,
                    "model": r.model_used,
                    "latency_ms": r.latency_ms,
                    "tokens_used": r.tokens_used,
                    "error": r.error,
                }
                for r in self.runs
            ],
            "skipped": list(self.skipped),
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Default gates / composers
# ---------------------------------------------------------------------------
def confidence_gate(threshold: float) -> GateFn:
    """Continue chain only when the prior step's confidence ≥ threshold AND
    no escalation flags are set in its output."""

    def _gate(run: AgentRun, ctx: ChainContext) -> bool:
        if run.error or not run.validation_ok or run.output is None:
            return False
        # Confidence is read from output (preferred) then from the lane decision.
        conf = run.output.get("confidence")
        if conf is None and run.lane_decision is not None:
            conf = run.lane_decision.confidence
        if conf is None or conf < threshold:
            return False
        # Don't auto-draft if the upstream agent flagged any escalation.
        flags = run.output.get("escalations") or []
        if isinstance(flags, list) and len(flags) > 0:
            return False
        # Don't auto-chain on Lane 3 items — too high stakes per spec.
        if run.lane_decision is not None and run.lane_decision.lane == 3:
            return False
        return True

    return _gate


def _default_composer(
    event_payload: dict[str, Any],
    prior_output: dict[str, Any],
    ctx: ChainContext,
) -> dict[str, Any]:
    """Fold the prior step's output into the next step's input.

    The convention is: pass the original event under `input` and the prior
    classification under `prior_classification`. Drafter prompts read both.
    """
    return {
        "input": event_payload,
        "prior_classification": prior_output,
        "chain_id": ctx.chain.chain_id,
    }


# ---------------------------------------------------------------------------
# run_chain — main entry point
# ---------------------------------------------------------------------------
async def run_chain(
    chain: Chain,
    event_payload: dict[str, Any],
    *,
    queue_client: QueueClient | None = None,
    config: Config | None = None,
    agent_factory: Callable[[str], Agent] | None = None,
    submit_combined: bool = True,
    workflow_override: str | None = None,
    priority: str = "normal",
) -> ChainResult:
    """Run `chain.steps` in order, fold outputs forward, and (optionally)
    submit ONE combined approval at the end.

    `agent_factory` lets tests inject mock agents per agent_id; in production
    we just call `Agent(agent_id, config=cfg, queue=queue)`.

    The combined approval's payload is the LAST successful step's output
    (so the UI's "What we're proposing" still reads sensibly), with the
    full `chain_outputs` attached at `payload.chain_outputs`.
    """
    cfg = config or get_config()
    queue = queue_client  # may be None; we'll lazily build if needed
    ctx = ChainContext(event=event_payload, chain=chain)

    factory = agent_factory or (lambda aid: Agent(aid, config=cfg, queue=queue))

    current_input: dict[str, Any] = event_payload
    last_output: dict[str, Any] | None = None
    last_run: AgentRun | None = None

    for idx, step in enumerate(chain.steps):
        agent = factory(step.agent_id)

        # First step gets the raw event payload; subsequent steps get composed.
        if idx == 0:
            step_input = current_input
        else:
            composer = step.compose_inputs or _default_composer
            assert last_output is not None  # noqa: S101
            step_input = composer(event_payload, last_output, ctx)

        try:
            run = await agent.run(
                step_input,
                submit_to_queue=False,  # chain submits ONE combined item at end
                workflow=workflow_override or chain.chain_id,
                priority=priority,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("chain.step.unhandled", chain=chain.chain_id, step=step.agent_id)
            ctx.errors.append(f"{step.agent_id}: unhandled: {e}")
            break

        ctx.runs.append(run)
        last_run = run

        if run.error or not run.validation_ok or run.output is None:
            ctx.errors.append(f"{step.agent_id}: {run.error or 'invalid output'}")
            # Stop the chain — no point feeding bad output forward.
            break

        last_output = run.output

        # Decide whether to continue to the NEXT step.
        is_last = idx == len(chain.steps) - 1
        if not is_last:
            gate = step.gate
            if gate is not None and not gate(run, ctx):
                # Mark all remaining steps as skipped.
                for skipped in chain.steps[idx + 1 :]:
                    ctx.skipped.append(skipped.agent_id)
                break

    result = ChainResult(
        chain_id=chain.chain_id,
        runs=ctx.runs,
        skipped=ctx.skipped,
        errors=ctx.errors,
    )

    # Submit one combined queue item for the chain (if any step succeeded).
    if submit_combined and last_run is not None and last_run.validation_ok and last_run.output is not None:
        # Build the submission payload off the last successful run, but
        # attach the full chain_outputs so the UI can render every step.
        submit_payload = _build_combined_payload(
            last_run=last_run,
            chain_result=result,
            event_payload=event_payload,
            workflow=workflow_override or chain.chain_id,
            priority=priority,
        )
        result.submitted_payload = submit_payload

        own_queue = queue is None
        q = queue or QueueClient(cfg)
        try:
            created = await q.create_approval(submit_payload)
            result.submitted_approval_id = created.get("id")
            log.info(
                "chain.submitted",
                chain=chain.chain_id,
                approval_id=result.submitted_approval_id,
                steps=[r.agent_id for r in result.runs],
            )
        except Exception as e:  # noqa: BLE001
            log.error("chain.submit_fail", chain=chain.chain_id, err=str(e))
            result.errors.append(f"submit: {e}")
        finally:
            if own_queue:
                await q.aclose()

    return result


def _build_combined_payload(
    *,
    last_run: AgentRun,
    chain_result: ChainResult,
    event_payload: dict[str, Any],
    workflow: str,
    priority: str,
) -> dict[str, Any]:
    """Build the ApprovalCreate body for a chain's combined queue item."""
    decision = last_run.lane_decision
    lane = decision.lane if decision else 2
    confidence = decision.confidence if decision else last_run.output.get("confidence")  # type: ignore[union-attr]
    reasoning = "; ".join(decision.reasons) if decision else ""

    payload = dict(last_run.output or {})
    payload["chain_outputs"] = chain_result.to_chain_outputs()
    payload["chain_id"] = chain_result.chain_id

    return {
        "agent_id": last_run.agent_id,
        "agent_version": last_run.agent_version,
        "workflow": workflow,
        "lane": lane,
        "priority": priority,
        "target_system": "none",
        "payload": payload,
        "agent_confidence": confidence,
        "agent_reasoning": reasoning or f"Chain {chain_result.chain_id} completed.",
        "agent_model": last_run.model_used,
        "agent_prompt_version": last_run.prompt_version_hash[:16],
        "agent_input_hash": last_run.input_hash,
        "agent_output_hash": last_run.output_hash,
        "required_approvers": ["owner", "partner"] if lane == 3 else [],
    }


# ---------------------------------------------------------------------------
# Built-in chain declarations (Phase F.1)
# ---------------------------------------------------------------------------
RFI_CHAIN = Chain(
    chain_id="rfi.full_triage",
    event_kinds=("rfi.new", "rfi.created"),
    steps=(
        Step("rfi-triage", gate=confidence_gate(0.7)),
        Step("rfi-drafter"),
    ),
)

SUBMITTAL_CHAIN = Chain(
    chain_id="submittal.full_review",
    event_kinds=("submittal.new", "submittal.created"),
    steps=(
        Step("submittal-triage", gate=confidence_gate(0.7)),
        Step("submittal-spec-validator"),
    ),
)

DFR_CHAIN = Chain(
    chain_id="dfr.synthesis",
    event_kinds=("dfr.new", "dfr.posted"),
    steps=(Step("dfr-synthesizer"),),
)

PROCUREMENT_CHAIN = Chain(
    chain_id="po.update",
    event_kinds=("procurement.update", "po.update"),
    steps=(Step("procurement-watch"),),
)

DEFAULT_CHAINS: tuple[Chain, ...] = (
    RFI_CHAIN,
    SUBMITTAL_CHAIN,
    DFR_CHAIN,
    PROCUREMENT_CHAIN,
)


def chain_for_event(
    event_kind: str, chains: tuple[Chain, ...] = DEFAULT_CHAINS
) -> Chain | None:
    for c in chains:
        if event_kind in c.event_kinds:
            return c
    return None


# ---------------------------------------------------------------------------
# Workflow-assignment DATA OVERLAY (ADK_AGENTS_DESIGN.md §4)
# ---------------------------------------------------------------------------
# Base chains above are CODE. An APPROVED workflow_assignment row is DATA that
# overrides which agent_id runs at a given stage_key ("change representation,
# not substance"). Unapproved assignments are INERT and never reach here — the
# overlay map only ever contains approved rows (see
# agent-cloud app/workflow_assignments.approved_overlay). This is the
# structural enforcement of the safety invariant: no approved row ⇒ no
# override ⇒ zero workflow mutation by an unapproved agent.
#
# stage_key convention: a stage is identified by the base step's agent_id
# (the natural, stable stage handle). An overlay entry
# (chain_id, stage_key) -> agent_id replaces the step whose agent_id ==
# stage_key with the assigned agent_id. If stage_key matches no existing step
# it is APPENDED as a new terminal stage (insert semantics per §4).


def stage_keys(chain: Chain) -> list[str]:
    """The stage handles for a chain (each step's agent_id)."""
    return [s.agent_id for s in chain.steps]


def apply_overlay(
    chain: Chain,
    overlay: dict[tuple[str, str], str],
) -> Chain:
    """Return a new Chain with approved assignments applied.

    `overlay` maps (chain_id, stage_key) -> agent_id. Only entries whose
    chain_id matches this chain are considered. Overriding a stage preserves
    that step's gate/composer (only the agent_id changes); an unmatched
    stage_key is appended as a new terminal step.

    Passing an empty overlay returns an equivalent chain (base behavior),
    so callers can always route through this function safely.
    """
    relevant = {
        sk: aid for (cid, sk), aid in overlay.items() if cid == chain.chain_id
    }
    if not relevant:
        return chain

    existing_keys = set(stage_keys(chain))
    new_steps: list[Step] = []
    for step in chain.steps:
        if step.agent_id in relevant:
            new_steps.append(
                Step(
                    agent_id=relevant[step.agent_id],
                    gate=step.gate,
                    compose_inputs=step.compose_inputs,
                )
            )
        else:
            new_steps.append(step)
    # Insert semantics: an approved assignment for a stage_key that isn't an
    # existing step appends a new terminal stage running the assigned agent.
    for sk, aid in relevant.items():
        if sk not in existing_keys:
            new_steps.append(Step(agent_id=aid))

    return Chain(
        chain_id=chain.chain_id,
        event_kinds=chain.event_kinds,
        steps=tuple(new_steps),
    )


def resolve_chain(
    event_kind: str,
    overlay: dict[tuple[str, str], str] | None = None,
    chains: tuple[Chain, ...] = DEFAULT_CHAINS,
) -> Chain | None:
    """chain_for_event + apply_overlay in one call. `overlay` defaults to
    empty (pure base-chain behavior)."""
    base = chain_for_event(event_kind, chains)
    if base is None:
        return None
    if not overlay:
        return base
    return apply_overlay(base, overlay)


__all__ = [
    "Chain",
    "ChainContext",
    "ChainResult",
    "Step",
    "DEFAULT_CHAINS",
    "RFI_CHAIN",
    "SUBMITTAL_CHAIN",
    "DFR_CHAIN",
    "PROCUREMENT_CHAIN",
    "chain_for_event",
    "confidence_gate",
    "run_chain",
    "apply_overlay",
    "resolve_chain",
    "stage_keys",
]


# Awaitable type alias used by tests
_AsyncChainFn = Callable[..., Awaitable[ChainResult]]
