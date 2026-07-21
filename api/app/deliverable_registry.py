"""Deliverable Registry — Phase E (roll deliverable spine to all 15 modules).

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
  - ``stage_key`` maps the deliverable type to its position in the 8-stage
    lifecycle (lifecycle.ts: origination | site_control | permitting | design |
    construction | commissioning | turnover | operations). This is code-only
    metadata: no DB column — threaded through _deliverable_out at query time.
  - Adding a new piloted type = one new entry here. Nothing else needs changing.

Phase B seeds exactly two pilots:

  cost_estimate   estimates module  ←  intent "estimate"
  rfi_response    projects module   ←  intent "rfi"

Phase C extends each entry with an ordered ``steps: list[ChainStep]`` that
defines the multi-step agent chain. Step A's output becomes Step B's input
context, building on prior work — never destructive.

Phase E extends the registry to ALL 15 modules, wiring every piloted intent
to a deliverable type with a 2-step chain (Step A drafts → Step B enriches).
The two existing Phase-B/C pilots are unchanged.

ChainStep fields:
  key           — short slug recorded in deliverable.meta for lineage tracing
  agent_name    — ADK agent name (same pool as INTENT_TO_ADK_AGENT)
  prompt_suffix — text appended to the seed_message to form this step's prompt.
                  Step B+ also receive the prior step's output as context.
  role          — human-readable label for logging/display

The two-step chains below cover all piloted intents. Phase D's HITL gate
(awaiting_human) is the terminal state after Step B. Keep the structure
declarative and extensible — adding a new step is a one-line change here.
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

    stage_key: str = ""
    """
    The lifecycle stage this deliverable belongs to. One of:
      origination | site_control | permitting | design | construction |
      commissioning | turnover | operations
    Mirrors the ``key`` field on LifecycleStage in web/lib/lifecycle.ts.
    Code-only metadata — no DB column; threaded through ``_deliverable_out``
    at query time and echoed in API output + web DeliverableSchema.
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

    terminal_hitl: str = "decision"
    """
    Phase G4: what kind of HITL gate the chain terminates at.

    ``"decision"``       — binary approve/reject gate (Phase D default).
                           Routes to the Approvals Queue (creates ApprovalItem).
    ``"co_development"`` — human contributes unique context the AI cannot source.
                           No ApprovalItem is created; resolved via
                           ``POST /v1/deliverables/{id}/resume``.

    Set to ``"co_development"`` for any deliverable type whose terminal step
    genuinely needs human-supplied information (RFI answers, field context,
    scope assumptions, drawing interpretations) rather than a simple approve/
    reject decision on an AI-produced artifact.
    """



# ---------------------------------------------------------------------------
# Registry — Phase E: full 15-module spine.
# ---------------------------------------------------------------------------
# ``deliverable_type`` is the key so callers can look up by type as well as
# by intent (via the ``INTENT_TO_DELIVERABLE`` helper below).
#
# Phase B / C pilots (cost_estimate, rfi_response) are UNCHANGED.
# Phase E adds 10 new entries covering all remaining piloted intents.
# ---------------------------------------------------------------------------

DELIVERABLE_REGISTRY: dict[str, DeliverableRegistryEntry] = {
    # ── Phase B/C Pilots (UNCHANGED) ──────────────────────────────────────
    "cost_estimate": DeliverableRegistryEntry(
        module_key="estimates",
        deliverable_type="cost_estimate",
        produced_by_intent="estimate",
        title_template="Cost estimate — {message}",
        stage_key="design",
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
        stage_key="construction",
        # G4: RFI responses are a canonical co-development gate — the human
        # (EOR, PM, design lead) must supply the actual technical answer to
        # the field question; the AI can only draft structure and context.
        # A binary approve/reject decision gate is insufficient here: the
        # human isn't just approving AI output, they're contributing the
        # information the AI cannot source from available documents.
        terminal_hitl="co_development",
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

    # ── Phase E: Projects — Schedule Package ──────────────────────────────
    # Intent: "schedule" → module: projects → stage: construction
    # The schedule monitor agent drafts a 3-week lookahead (Step A) then
    # enriches it with critical-path analysis and milestone status (Step B).
    "schedule_package": DeliverableRegistryEntry(
        module_key="projects",
        deliverable_type="schedule_package",
        produced_by_intent="schedule",
        title_template="Schedule package — {message}",
        stage_key="construction",
        steps=[
            ChainStep(
                key="schedule_draft",
                agent_name="quill_schedule_monitor",
                prompt_suffix=(
                    "You are performing Step A (Schedule Draft) of a schedule package. "
                    "Analyze the request, parse any schedule data provided, identify the "
                    "current critical path, and produce a structured 3-week lookahead with "
                    "activity sequences, durations, and resource notes."
                ),
                role="Schedule Draft / 3-Week Lookahead",
            ),
            ChainStep(
                key="schedule_analysis",
                agent_name="quill_schedule_monitor",
                prompt_suffix=(
                    "You are performing Step B (Critical Path Analysis & Milestone Update) of "
                    "a schedule package. Using the schedule draft from the prior step as your "
                    "input, perform a critical-path analysis, identify float per activity, "
                    "flag any activities with negative float or variance >5 days, and produce "
                    "a milestone status summary with baseline vs. forecast dates."
                ),
                role="Critical Path Analysis / Milestone Status",
            ),
        ],
    ),

    # ── Phase E: Contracts — Change Order Package ─────────────────────────
    # Intent: "contract" → module: contracts → stage: construction
    # The change order agent ingests the contract/CO request (Step A) then
    # performs clause risk analysis and produces a draft CO package (Step B).
    "change_order_package": DeliverableRegistryEntry(
        module_key="contracts",
        deliverable_type="change_order_package",
        produced_by_intent="contract",
        title_template="Change order package — {message}",
        stage_key="construction",
        steps=[
            ChainStep(
                key="contract_intake",
                agent_name="quill_change_order",
                prompt_suffix=(
                    "You are performing Step A (Contract Intake & Abstract) of a change order "
                    "package. Review the contract or change order request, extract key terms "
                    "(parties, scope, cost delta, schedule impact, contract clause references), "
                    "and produce a structured contract abstract and intake summary."
                ),
                role="Contract Intake / Abstract",
            ),
            ChainStep(
                key="co_draft",
                agent_name="quill_change_order",
                prompt_suffix=(
                    "You are performing Step B (Change Order Draft & Clause Analysis) of a "
                    "change order package. Using the contract abstract from the prior step as "
                    "your context, draft a complete change order document with: scope narrative, "
                    "cost breakdown, schedule delta, supporting clause references, and a risk "
                    "flag summary for any non-standard or high-risk clauses."
                ),
                role="Change Order Draft / Clause Risk Analysis",
            ),
        ],
    ),

    # ── Phase E: Sites — Site Assessment ──────────────────────────────────
    # Intents: site_evaluation, site_research, site_scoring, site_status
    # → module: sites → stage: site_control
    # The site evaluator produces an initial site candidate assessment (Step A)
    # then enriches with scoring, fatal flaws, and go/no-go recommendation (Step B).
    # Note: INTENT_TO_DELIVERABLE maps the PRIMARY intent (site_evaluation) here;
    # site_research/scoring/status also map to this type for consistent deliverable output.
    "site_assessment": DeliverableRegistryEntry(
        module_key="sites",
        deliverable_type="site_assessment",
        produced_by_intent="site_evaluation",
        title_template="Site assessment — {message}",
        stage_key="site_control",
        steps=[
            ChainStep(
                key="site_intake",
                agent_name="datasite_site_evaluator",
                prompt_suffix=(
                    "You are performing Step A (Site Intake & Initial Assessment) of a site "
                    "assessment. Review the site request, extract the address, program "
                    "requirements (MW load, acreage, fiber/connectivity), and produce a "
                    "structured initial site candidate summary with available metadata "
                    "(zoning, flood zone, estimated distance to substation, fiber carriers)."
                ),
                role="Site Intake / Initial Assessment",
            ),
            ChainStep(
                key="site_scoring",
                agent_name="datasite_site_evaluator",
                prompt_suffix=(
                    "You are performing Step B (Site Scoring & Go/No-Go Recommendation) of a "
                    "site assessment. Using the initial site assessment from the prior step as "
                    "your context, apply the weighted scoring model (power 30%, land/zoning 20%, "
                    "fiber 20%, water 10%, risk 20%), flag any fatal flaws, and produce a ranked "
                    "Site Scorecard with a Go/No-Go recommendation and brief rationale."
                ),
                role="Site Scoring / Go-No-Go Recommendation",
            ),
        ],
    ),

    # ── Phase E: Operations — Ops Report ──────────────────────────────────
    # Intents: facility_ops, campus, incident, uptime, pue
    # → module: operations → stage: operations
    # The facility ops agent drafts a field observation / ops status report (Step A)
    # then enriches with incident analysis, PUE/uptime metrics, and alerts (Step B).
    "ops_report": DeliverableRegistryEntry(
        module_key="operations",
        deliverable_type="ops_report",
        produced_by_intent="facility_ops",
        title_template="Ops report — {message}",
        stage_key="operations",
        steps=[
            ChainStep(
                key="ops_status_draft",
                agent_name="quill_facility_ops",
                prompt_suffix=(
                    "You are performing Step A (Ops Status Draft) of an operations report. "
                    "Review the facility/campus operations request, identify the scope "
                    "(PUE monitoring, uptime check, incident review, or general facility status), "
                    "and produce a structured ops status summary with current metrics, "
                    "open incidents, and field observation notes."
                ),
                role="Ops Status Draft",
            ),
            ChainStep(
                key="ops_analysis",
                agent_name="quill_facility_ops",
                prompt_suffix=(
                    "You are performing Step B (Ops Analysis & Alert Summary) of an operations "
                    "report. Using the ops status summary from the prior step as your context, "
                    "perform a trend analysis on PUE and uptime metrics, flag any threshold "
                    "breaches or anomalies, summarize open incidents with corrective action "
                    "status, and produce a final operations report with recommended next actions."
                ),
                role="Ops Analysis / Alert Summary",
            ),
        ],
    ),

    # ── Phase E: Supply Chain — Procurement Package ───────────────────────
    # Intents: supply_chain, equipment, vendor, procurement, lead_time, delivery
    # → module: supply-chain → stage: construction
    # The supply chain agent drafts an equipment/vendor assessment (Step A)
    # then enriches with lead-time analysis, critical-path flags, and PO draft (Step B).
    "procurement_package": DeliverableRegistryEntry(
        module_key="supply-chain",
        deliverable_type="procurement_package",
        produced_by_intent="supply_chain",
        title_template="Procurement package — {message}",
        stage_key="construction",
        steps=[
            ChainStep(
                key="procurement_intake",
                agent_name="quill_supply_chain",
                prompt_suffix=(
                    "You are performing Step A (Procurement Intake & Equipment Spec) of a "
                    "procurement package. Review the supply chain or equipment request, "
                    "identify the equipment type, specifications, vendor candidates, and "
                    "site-need date, and produce a structured equipment specification "
                    "summary and Long-Lead Equipment Register entry."
                ),
                role="Procurement Intake / Equipment Spec",
            ),
            ChainStep(
                key="lead_time_analysis",
                agent_name="quill_supply_chain",
                prompt_suffix=(
                    "You are performing Step B (Lead Time Analysis & Procurement Plan) of a "
                    "procurement package. Using the equipment specification from the prior step "
                    "as your context, compute the must-order-by date based on current market "
                    "lead times (reference: utility transformers 52–104 weeks, MV switchgear "
                    "52–78 weeks, EDGs 40–65 weeks, chillers 40–52 weeks, UPS 26–52 weeks), "
                    "flag any at-risk items, and produce a draft procurement schedule with "
                    "vendor shortlist and recommended RFQ approach."
                ),
                role="Lead Time Analysis / Procurement Plan",
            ),
        ],
    ),

    # ── Phase E: Finance — Finance Report ─────────────────────────────────
    # Intent: "finance" → module: finance → stage: construction
    # The finance agent produces a budget/cost status draft (Step A) then
    # enriches with EAC, cash flow forecast, and variance analysis (Step B).
    "finance_report": DeliverableRegistryEntry(
        module_key="finance",
        deliverable_type="finance_report",
        produced_by_intent="finance",
        title_template="Finance report — {message}",
        stage_key="construction",
        steps=[
            ChainStep(
                key="cost_status_draft",
                agent_name="quill_finance",
                prompt_suffix=(
                    "You are performing Step A (Cost Status Draft) of a finance report. "
                    "Review the finance request, identify the scope (budget tracker, pay app "
                    "review, invoice status, or cash position), and produce a structured "
                    "cost status summary with budget vs. committed vs. actual figures "
                    "and any flagged line-item discrepancies."
                ),
                role="Cost Status Draft",
            ),
            ChainStep(
                key="finance_analysis",
                agent_name="quill_finance",
                prompt_suffix=(
                    "You are performing Step B (EAC & Variance Analysis) of a finance report. "
                    "Using the cost status summary from the prior step as your context, compute "
                    "the Estimate at Completion (EAC), identify budget variance by cost code, "
                    "flag any cost codes trending over budget or with contingency erosion risk, "
                    "and produce a final finance report with cash flow impact summary and "
                    "recommended corrective actions."
                ),
                role="EAC / Variance Analysis",
            ),
        ],
    ),

    # ── Phase E: Compliance — Compliance Report ───────────────────────────
    # Intent: "compliance" → module: compliance → stage: permitting
    # The compliance agent drafts a permit/obligation status summary (Step A)
    # then enriches with calendar alerts, COI tracking, and risk flags (Step B).
    "compliance_report": DeliverableRegistryEntry(
        module_key="compliance",
        deliverable_type="compliance_report",
        produced_by_intent="compliance",
        title_template="Compliance report — {message}",
        stage_key="permitting",
        steps=[
            ChainStep(
                key="compliance_intake",
                agent_name="quill_compliance",
                prompt_suffix=(
                    "You are performing Step A (Compliance Intake & Permit Status) of a "
                    "compliance report. Review the compliance request, identify the scope "
                    "(permit register, regulatory obligations, insurance COIs, lien waivers, "
                    "or audit readiness), and produce a structured compliance status summary "
                    "with open items, responsible parties, and due dates."
                ),
                role="Compliance Intake / Permit Status",
            ),
            ChainStep(
                key="compliance_analysis",
                agent_name="quill_compliance",
                prompt_suffix=(
                    "You are performing Step B (Compliance Risk Analysis & Alert Calendar) of "
                    "a compliance report. Using the compliance status summary from the prior "
                    "step as your context, flag any obligations past due or within 30/60/90 "
                    "days, identify missing insurance certificates or lien waivers, highlight "
                    "any NOV/NOD risk, and produce a final compliance report with a prioritized "
                    "action calendar and risk-rated findings."
                ),
                role="Compliance Risk Analysis / Alert Calendar",
            ),
        ],
    ),

    # ── Phase E: Sales — Pipeline Summary ────────────────────────────────
    # Intents: sales, pipeline → module: sales → stage: origination
    # The sales agent ingests deal/pipeline data (Step A) then enriches with
    # capacity feasibility analysis and pipeline forecast (Step B).
    "pipeline_summary": DeliverableRegistryEntry(
        module_key="sales",
        deliverable_type="pipeline_summary",
        produced_by_intent="sales",
        title_template="Pipeline summary — {message}",
        stage_key="origination",
        steps=[
            ChainStep(
                key="pipeline_intake",
                agent_name="quill_sales",
                prompt_suffix=(
                    "You are performing Step A (Pipeline Intake & Lead Summary) of a pipeline "
                    "summary. Review the sales or pipeline request, extract deal details "
                    "(company, MW requirement, timeline, deal stage, geography, SLA), and "
                    "produce a structured pipeline record with customer requirements summary "
                    "and current deal-stage classification."
                ),
                role="Pipeline Intake / Lead Summary",
            ),
            ChainStep(
                key="pipeline_analysis",
                agent_name="quill_sales",
                prompt_suffix=(
                    "You are performing Step B (Pipeline Analysis & Capacity Feasibility) of "
                    "a pipeline summary. Using the pipeline record from the prior step as your "
                    "context, analyze the weighted deal pipeline vs. available capacity, flag "
                    "any overcommitment risk, draft a prospect pipeline report with deal aging, "
                    "next-action prompts, and a capacity feasibility assessment for top deals."
                ),
                role="Pipeline Analysis / Capacity Feasibility",
            ),
        ],
    ),

    # ── Phase E: Customers — Customer Summary ─────────────────────────────
    # Intent: "customer_success" → module: customers → stage: operations
    # The customer success agent triages tickets and SLA status (Step A) then
    # enriches with QBR package draft and escalation summary (Step B).
    "customer_summary": DeliverableRegistryEntry(
        module_key="customers",
        deliverable_type="customer_summary",
        produced_by_intent="customer_success",
        title_template="Customer summary — {message}",
        stage_key="operations",
        steps=[
            ChainStep(
                key="customer_intake",
                agent_name="quill_customer_success",
                prompt_suffix=(
                    "You are performing Step A (Customer Intake & Ticket Triage) of a customer "
                    "summary. Review the customer success request, identify the customer and "
                    "scope (ticket triage, SLA status check, health score, or QBR preparation), "
                    "and produce a structured customer status summary with open tickets by "
                    "severity, SLA performance metrics, and current health score."
                ),
                role="Customer Intake / Ticket Triage",
            ),
            ChainStep(
                key="customer_analysis",
                agent_name="quill_customer_success",
                prompt_suffix=(
                    "You are performing Step B (Customer Analysis & QBR Package Draft) of a "
                    "customer summary. Using the customer status summary from the prior step as "
                    "your context, analyze SLA performance trends, flag any breach risk or "
                    "at-risk churn indicators, produce an escalation summary for P1/P2 tickets "
                    "aged >SLA, and draft a QBR package outline with performance narrative and "
                    "recommended talking points."
                ),
                role="Customer Analysis / QBR Package Draft",
            ),
        ],
    ),

    # ── Phase E: Intelligence — Executive Brief ───────────────────────────
    # Intent: "intelligence" → module: intelligence → stage: operations
    # The intelligence agent aggregates cross-module KPI data (Step A) then
    # produces a risk-scored executive brief with escalation summary (Step B).
    "exec_brief": DeliverableRegistryEntry(
        module_key="intelligence",
        deliverable_type="exec_brief",
        produced_by_intent="intelligence",
        title_template="Executive brief — {message}",
        stage_key="operations",
        steps=[
            ChainStep(
                key="data_aggregation",
                agent_name="quill_intelligence",
                prompt_suffix=(
                    "You are performing Step A (Data Aggregation & KPI Summary) of an executive "
                    "brief. Review the intelligence or briefing request, aggregate the relevant "
                    "cross-module status data (projects, finance, contracts, compliance, supply "
                    "chain, operations, customers), and produce a structured KPI dashboard "
                    "summary with RAG (Red/Amber/Green) status per domain."
                ),
                role="Data Aggregation / KPI Summary",
            ),
            ChainStep(
                key="executive_narrative",
                agent_name="quill_intelligence",
                prompt_suffix=(
                    "You are performing Step B (Executive Narrative & Risk Brief) of an executive "
                    "brief. Using the KPI dashboard summary from the prior step as your context, "
                    "identify the top 3–5 risks requiring executive attention, draft a concise "
                    "Weekly Executive Brief (top risks, key decisions needed, wins, cash status), "
                    "and produce an escalation summary for any items past SLA or in red RAG status."
                ),
                role="Executive Narrative / Risk Brief",
            ),
        ],
    ),
}

# Convenience reverse-index: intent → registry entry (only piloted intents).
# Phase E: 12 piloted intents total (2 original + 10 new).
# Multi-intent types (e.g. sites has 4 intents) — the primary intent is the
# canonical mapping; secondary intents are aliased below.
INTENT_TO_DELIVERABLE: dict[str, DeliverableRegistryEntry] = {
    entry.produced_by_intent: entry
    for entry in DELIVERABLE_REGISTRY.values()
}

# ── Phase E: Secondary intent aliases ─────────────────────────────────────
# Some deliverable types are produced by multiple intents. The canonical
# produced_by_intent handles the primary flow; these aliases ensure the
# producer in routes/requests.py also fires for secondary intents that
# should produce the SAME deliverable type.
#
# Sites: site_research, site_scoring, site_status → same site_assessment type
_SITES_ENTRY = DELIVERABLE_REGISTRY["site_assessment"]
INTENT_TO_DELIVERABLE["site_research"] = _SITES_ENTRY
INTENT_TO_DELIVERABLE["site_scoring"] = _SITES_ENTRY
INTENT_TO_DELIVERABLE["site_status"] = _SITES_ENTRY

# Operations: campus, incident, uptime, pue → same ops_report type
_OPS_ENTRY = DELIVERABLE_REGISTRY["ops_report"]
INTENT_TO_DELIVERABLE["campus"] = _OPS_ENTRY
INTENT_TO_DELIVERABLE["incident"] = _OPS_ENTRY
INTENT_TO_DELIVERABLE["uptime"] = _OPS_ENTRY
INTENT_TO_DELIVERABLE["pue"] = _OPS_ENTRY

# Supply Chain: equipment, vendor, procurement, lead_time, delivery → same procurement_package
_SC_ENTRY = DELIVERABLE_REGISTRY["procurement_package"]
INTENT_TO_DELIVERABLE["equipment"] = _SC_ENTRY
INTENT_TO_DELIVERABLE["vendor"] = _SC_ENTRY
INTENT_TO_DELIVERABLE["procurement"] = _SC_ENTRY
INTENT_TO_DELIVERABLE["lead_time"] = _SC_ENTRY
INTENT_TO_DELIVERABLE["delivery"] = _SC_ENTRY

# Sales: pipeline → same pipeline_summary type
_SALES_ENTRY = DELIVERABLE_REGISTRY["pipeline_summary"]
INTENT_TO_DELIVERABLE["pipeline"] = _SALES_ENTRY

# ── Journey-step intents (web/lib/journey.ts) ─────────────────────────────
# The 5-phase journey UI submits step-specific intent strings. These were
# previously absent from the registry, so submitting a journey step fell
# through classify_intent() and produced the wrong artifact (or none). Map
# each journey intent onto the existing, tested deliverable generator for its
# module so the step produces the RIGHT deliverable type end-to-end.
_ESTIMATE_ENTRY = DELIVERABLE_REGISTRY["cost_estimate"]
_CONTRACT_ENTRY = DELIVERABLE_REGISTRY["change_order_package"]
_SCHEDULE_ENTRY = DELIVERABLE_REGISTRY["schedule_package"]
_RFI_ENTRY = DELIVERABLE_REGISTRY["rfi_response"]

# Estimate phase
INTENT_TO_DELIVERABLE["cost_takeoff"] = _ESTIMATE_ENTRY
INTENT_TO_DELIVERABLE["estimate_package"] = _ESTIMATE_ENTRY
# Contract phase
INTENT_TO_DELIVERABLE["contract_draft"] = _CONTRACT_ENTRY
INTENT_TO_DELIVERABLE["contract_review"] = _CONTRACT_ENTRY
INTENT_TO_DELIVERABLE["contract_execute"] = _CONTRACT_ENTRY
INTENT_TO_DELIVERABLE["change_order"] = _CONTRACT_ENTRY
# Project phase
INTENT_TO_DELIVERABLE["schedule_build"] = _SCHEDULE_ENTRY
INTENT_TO_DELIVERABLE["rfi_management"] = _RFI_ENTRY
# Progress + Operate phase → operations report generator
INTENT_TO_DELIVERABLE["progress_report"] = _OPS_ENTRY
INTENT_TO_DELIVERABLE["commissioning"] = _OPS_ENTRY
INTENT_TO_DELIVERABLE["owner_reporting"] = _OPS_ENTRY
INTENT_TO_DELIVERABLE["operations_status"] = _OPS_ENTRY
