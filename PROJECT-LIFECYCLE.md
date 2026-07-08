Quill — Project Lifecycle, Modules, Agents, Deliverables & Human-in-the-Loop Map

Author: Axe · Date: 2026-07-08 · Status: Code-grounded reference (v1)
Scope: How a capital project moves from site selection → construction → handover to operations inside Quill, which modules and agents engage at each point, what deliverables are produced, and every human-in-the-loop (HITL) decision point — counted, so human effort is quantifiable.

Grounding note: This is built from the actual codebase (quill-platform), not from prose. State machines, enums, agents, and approval workflows are all extracted from live code. Where a stage is not yet automated, it is labeled NOT YET AUTOMATED so we do not overstate what the platform does today.

================================================================================
0. EXECUTIVE SUMMARY
================================================================================

Quill is an administrative operating system for capital execution. It takes a project from origination through operations and automates the paperwork, analysis, drafting, and tracking at each stage — while keeping a human approval gate on anything that commits the business (money, contracts, external system writes).

The end-to-end chain spans FIVE macro-stages and SIX construction phases:

  ORIGINATION → SITE SELECTION → [PROJECT: site_control → permitting → design →
  construction → commissioning → turnover] → OPERATIONS

The human's job shifts from "doing the administrative work" to "approving the work the agents did." Every automated action that has real-world consequence surfaces as a countable approval item with a lane (auto / single-sig / dual-sig), an owner, and an approve/reject outcome. That is the mechanism by which we quantify human effort: count the approval items per stage.

TOTAL HITL GATES ACROSS THE LIFECYCLE (current build): ~14 discrete decision points (detailed in §5), of which ~9 are single-signature (one approver) and the remainder are either dual-signature (high-value/contractual) or auto-lane (logged, no human unless flagged).

================================================================================
1. THE LIFECYCLE AT A GLANCE
================================================================================

Macro-stage        Module(s)              Primary output                         HITL gates
-----------------  ---------------------  -------------------------------------  ----------
1 Origination      pipeline               Qualified deal → decision to pursue    1 (soft)
2 Site selection   sites (DataSite)       Feasibility assessment + site score    1
3 Advance→Project  sites → projects       Project created from a won site        1 (Lane 2)
4 Permitting       projects, compliance   Permit tracker, regulatory checklist   1–2
5 Design           projects, estimates    AACE classification + cost/schedule    2
6 Construction     projects, contracts,   Contracts, change orders, budget,      3–4
                   finance, supply_chain  procurement, status updates
7 Commissioning    projects, operations   Commissioning checklist, punch list    1
8 Turnover         projects → operations  Handover package → Campus created      1
9 Operations       operations             Live facility monitoring, incidents    ongoing

(Stage numbering: stages 4–8 are the six code-defined Project phases: site_control, permitting, design, construction, commissioning, turnover.)

================================================================================
2. THE MODULES (functional domains)
================================================================================

Each module is an API surface (api/app/routes/<module>.py) over a set of DB tables. These are the building blocks the lifecycle is assembled from.

- pipeline        — Sales/origination deals. Stages: prospect, qualified, proposal, negotiating, won, lost. (models_pipeline.py)
- sites (DataSite)— Site feasibility. Lives in the EXTERNAL datasite-agents Cloud Run service; Quill proxies to it (routes/sites.py). Google Drive folder intake → document analysis → weighted site score + verdict. Quill stores only the intake record (site_drive_intakes).
- projects        — The core construction record. Phases: site_control, permitting, design, construction, commissioning, turnover. Status: active, on_hold, complete, cancelled. Sub-records: milestones, project log (general/issue/milestone/decision), document links. (models_projects.py)
- estimates       — Drawing-driven cost + schedule. State: queued → extracting → classifying → estimating → done (or failed). Produces an AACE classification and a cost/schedule package. (models.py Estimate)
- contracts       — Contract lifecycle. State: uploaded → extracting → extracted → reviewing → reviewed → drafting → drafted (or failed). Types: owner_gc, subcontract, change_order, purchase_order, letter_of_intent, nda, msa, equipment_lease, insurance_certificate, lien_waiver, other. (models.py Contract)
- finance         — Portfolio + project financials (budget, committed, forecast). Rolls up project.budget_usd / committed_usd / forecast_usd. (routes/finance.py)
- supply_chain    — Procurement / long-lead item tracking. (routes/supply_chain.py)
- compliance      — Obligations (open/complete/overdue/waived), regulatory items (open/complete/in_progress/waived), insurance (active/expiring/expired/cancelled), checklists. (models_compliance.py)
- operations      — Post-turnover facility ("Campus"). Status: commissioning, live, maintenance, decommissioned. Incidents (open/investigating/resolved/closed), monitoring agents. (models_operations.py)
- customers       — Support/relationship tickets (open/in_progress/resolved/closed). (models_customers.py)
- documents       — Document store + links; artifacts generated by agents land here. (models.py Document)
- approvals       — The HITL engine. Every agent action requiring human sign-off is an approval_item with a lane, priority, target system, and audit hash chain. (routes/approvals.py, services/approvals.py)
- intelligence    — Executive layer: cross-module exceptions + morning brief. (routes/intelligence.py)
- agent-cloud     — The conversational agent platform (personal/quill/custom agents) that can read Quill data and drive these workflows through the approval system.

================================================================================
3. THE AGENTS (what runs, and when)
================================================================================

Quill uses three families of agents. They are the "labor" that produces deliverables; the human is the "approver."

3.1 DISPATCH LOOPS (runtime/runtime/*_dispatcher.py) — the workflow engine
These are claim-lease background loops that watch for records in a given state, run a specialist agent, and file an approval item with the result. They are the automation heartbeat of the lifecycle.

- triage_dispatcher        — Classifies inbound items/requests and routes them.
- classification_dispatcher— Estimates: runs the design-classifier agent on queued estimates → files an AACE classification approval.
- estimator_dispatcher     — Estimates: runs the estimator-scheduler agent on estimates in "estimating" → files a cost/schedule package approval.
- contract_dispatcher      — Contracts: runs the contract-extractor agent on new contracts → files a contract-extraction approval.
- contract_review_dispatcher — Contracts: runs the contract-reviewer agent on extracted contracts → files a contract-review approval.
- contract_draft_dispatcher— Contracts: drives the drafting flow → files a contract-draft approval.

3.2 ADK SPECIALIST AGENTS (external quill-adk-agents + datasite-agents services)
These are the reasoning workers the dispatch loops invoke. They run 100% in Cloud Run. Representative roster by stage:

- Site selection:  DataSite document analyst(s) — read Drive docs, extract site attributes, score feasibility.
- Design/estimate: design-classifier (AACE class), estimator-scheduler (cost + schedule package).
- Contracts:       contract-extractor (pull key terms), contract-reviewer (risk flags), contract-drafter (generate drafts).
- Cross-cutting:   intelligence/brief agent (exceptions + morning brief).

3.3 AGENT-CLOUD AGENTS (the conversational layer)
- personal — general assistant per user (memory on, reminders, web search, Quill tools).
- quill    — a chat agent over the Quill API (reads flow freely; every write routes to the approval queue). Answers "what's our committed cost on Project X?" and can initiate workflows.
- (custom) — user-created agents via the Agent Builder.

KEY ARCHITECTURAL RULE: Agents PROPOSE, humans DISPOSE. Every agent write becomes an approval item (workflow agentcloud.<action>) plus a proposal row; the agent is told the write is "pending human approval." Nothing external is mutated without a human decision.

================================================================================
4. DELIVERABLES BY STAGE (what artifacts get produced)
================================================================================

Stage              Deliverable(s) produced                                         Where it lives
-----------------  --------------------------------------------------------------  ------------------------
Origination        Qualified deal record; pursue/no-pursue decision                pipeline (Deal)
Site selection     Feasibility assessment; weighted site score + verdict;          DataSite; site_drive_intakes;
                   Drive document intake summary                                    documents
Advance→Project    New Project (phase=site_control) seeded from the site           projects (Project)
Permitting         Permit tracker entries; regulatory checklist; obligations       compliance; project milestones
Design             AACE cost classification; cost + schedule package               estimates; documents
Construction       Executed contracts; change orders; purchase orders;             contracts; finance;
                   budget vs committed vs forecast; procurement/long-lead log;      supply_chain; project log
                   project status updates; risk/issue log                           
Commissioning      Commissioning checklist; punch list; readiness sign-off         compliance; project milestones
Turnover           Handover package; as-builts + O&M doc links; Campus record       documents; operations (Campus)
Operations         Live monitoring; incident records; maintenance log              operations

Recurring cross-lifecycle deliverables (intelligence module): morning brief (structured portfolio summary) and cross-module exception list — produced continuously, not tied to one stage.

================================================================================
5. HUMAN-IN-THE-LOOP (HITL) POINTS — THE EFFORT MODEL
================================================================================

This is the section that answers "how much human effort does a project require?" Every HITL point below is a real approval_item in the system with:
  - a LANE:     Lane 1 = auto (logged, no human unless flagged) · Lane 2 = single-signature (one approver) · Lane 3 = dual-signature (two approvers, high value/contractual)
  - an OWNER:   who must act (owner / partner roles)
  - an OUTCOME: approve / edit-then-approve / reject / escalate
  - an AUDIT:   hash-chained record of the decision

5.1 GATE-BY-GATE (in lifecycle order)

#   Stage           Gate (approval workflow)                    Lane   Owner        Trigger → on approve
--  --------------  ------------------------------------------  -----  -----------  ----------------------------------
1   Origination     Pursue deal (soft/business gate)            n/a    owner        Human marks deal "won" → eligible to advance
2   Site selection  Accept feasibility / site score             2      owner        DataSite returns verdict → human accepts site
3   Advance→Project site_advance.create_project                 2      owner        POST /sites/{id}/advance → creates Project (phase=site_control)
4   Permitting      Regulatory/permit checklist sign-off        2      owner        Permit items complete → human confirms permit readiness
5   Design          aace_classification.publish                 2      owner        classification_dispatcher files it → stamps estimate, advances to estimating
6   Design          cost_schedule_package.publish               2/3    owner(/ptnr) estimator_dispatcher files it → stamps estimate "done"
7   Construction    contract_extraction.publish                 2      owner        contract_dispatcher files it → stores extracted fields
8   Construction    contract_review.publish                     2      owner        contract_review_dispatcher files it → stores review artifact
9   Construction    contract_draft.publish                      2/3    owner(/ptnr) contract_draft_dispatcher files it → produces contract draft
10  Construction    change_order / commitment (finance write)   3      owner+ptnr   Agent proposes a cost commitment → dual sign-off
11  Construction    external system write (Procore/P6/ACC)      2/3    owner        Agent writes to an external PM system → human approves the push
12  Commissioning   commissioning checklist sign-off            2      owner        Punch list clear → human confirms commissioning complete
13  Turnover        handover / turnover package sign-off        2      owner        Handover package assembled → human approves turnover
14  Turnover        promote Project → Campus (operations)       2      owner        Manual promotion → creates Campus (operations begins)

Notes:
- Gates 1 and 4 are partially manual today (business/checklist confirmations); gates 5–9 are fully agent-driven with a single approval each; gate 14 is a manual promotion (no automated transition in code yet — labeled NOT YET AUTOMATED).
- Any Lane-1 (auto) action still writes an audit record and can be escalated to a human if an anomaly/budget/rate rule trips — so "auto" is not "invisible."

5.2 HITL COUNT PER STAGE (the effort quantification)

Stage            Human decision points   Typical lane mix
---------------  ----------------------  --------------------------------
Origination      1 (soft)                business judgment
Site selection   1                       1× single-sig
Advance→Project  1                       1× single-sig (Lane 2)
Permitting       1–2                     single-sig
Design           2                       single-sig (package may be dual)
Construction     3–4                     mix of single- and dual-sig; the money/contract-heavy stage
Commissioning    1                       single-sig
Turnover         1–2                     single-sig + manual promotion
Operations       ongoing (exception-based) mostly Lane-1 auto + incident escalations

BASELINE HUMAN EFFORT PER PROJECT (happy path, current build): ~10–14 discrete approvals from won-deal to operations. Construction is the heaviest (contracts + money). Everything else the agents assemble and the human simply approves.

EFFORT LEVERS (how to reduce human touches over time):
- Promote proven workflows from Lane 2 → Lane 1 (auto) once trust is established (TrustTier: tier-0-mandatory → tier-1-spotcheck → tier-2-auto).
- Batch same-stage approvals (e.g., all permit items) into a single decision.
- Reserve dual-sig (Lane 3) strictly for money and binding contracts.

================================================================================
6. HOW THIS FEEDS THE APP (the Lifecycle view — next deliverable)
================================================================================

The doc above is the spec for a new app view:
- A horizontal lifecycle tracker showing the 6 project phases (+ origination and operations bookends), with the current phase highlighted for any given project.
- Each phase node shows: deliverables produced/expected, agents engaged, and OPEN HITL gates (with a badge count of pending approvals) so a user instantly sees "what's waiting on me here."
- Drill-down: clicking a phase opens the relevant module records (e.g., clicking Design shows the estimate + its classification/package approvals; clicking Construction shows contracts, change orders, budget).
- Onboarding value: a new user sees the whole capital-execution process on one screen, understands where their project is, and knows exactly which decisions are theirs to make.

This turns the abstract "we automate PM" into a concrete, walkable map — which is also the clearest way to explain the product to a new person.

================================================================================
APPENDIX — SOURCE OF TRUTH (code references)
================================================================================
- Project phases/status:   api/app/models_projects.py (VALID_PHASES, VALID_STATUSES, Project, ProjectMilestone, ProjectLogEntry)
- Deal pipeline:           api/app/models_pipeline.py (VALID_DEAL_STAGES)
- Sites/DataSite proxy:    api/app/routes/sites.py; api/app/services/site_drive_intake.py; api/app/models_sites.py
- Estimates state machine: api/app/models.py (Estimate); runtime/runtime/classification_dispatcher.py; runtime/runtime/estimator_dispatcher.py
- Contracts state machine: api/app/models.py (Contract); runtime/runtime/contract_dispatcher.py; contract_review_dispatcher.py; contract_draft_dispatcher.py
- Approvals/HITL:          api/app/enums.py (Lane, ApprovalStatus, TrustTier, TargetSystem); api/app/routes/approvals.py; api/app/services/approvals.py
- Operations/Campus:       api/app/models_operations.py (VALID_CAMPUS_STATUSES)
- Compliance:              api/app/models_compliance.py
- Intelligence:            api/app/routes/intelligence.py
