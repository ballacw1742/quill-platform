/**
 * lifecycle.ts — Canonical project-lifecycle metadata (single source of truth
 * for the Lifecycle tracker UI). Mirrors PROJECT-LIFECYCLE.md and the code
 * enums in api/app/models_projects.py (VALID_PHASES) + models_pipeline.py +
 * models_operations.py.
 *
 * The tracker renders the 6 construction PHASES as the core, bookended by the
 * Origination (deal pipeline) and Operations (Campus) macro-stages. Each stage
 * carries: what deliverables are produced, which agents engage, which app
 * module holds the records (for drill-down), and the human-in-the-loop (HITL)
 * gate(s) with their approval lane so the UI can show "what's waiting on me."
 */

export type Lane = 1 | 2 | 3; // 1=auto, 2=single-sig, 3=dual-sig

export type LifecycleHitl = {
  /** Human-readable gate name. */
  label: string;
  /** Approval workflow id(s) that back this gate (used to count open approvals). */
  workflows: string[];
  lane: Lane;
  /** Who must act. */
  owner: string;
};

export type LifecycleStage = {
  key: string;
  label: string;
  /** short one-liner for the phase node. */
  blurb: string;
  /** true for the 6 code-defined Project.phase values; false for bookend macro-stages. */
  isProjectPhase: boolean;
  /** deliverables produced in this stage. */
  deliverables: string[];
  /** agents engaged in this stage. */
  agents: string[];
  /** app route to drill into for this stage's records ({id} substituted per-project). */
  drilldown?: { label: string; href: string }[];
  /** HITL gates in this stage. */
  hitl: LifecycleHitl[];
};

/**
 * Full ordered lifecycle. Indexes 1..6 are the Project.phase values; index 0
 * (Origination) and index 7 (Operations) are the bookend macro-stages.
 */
export const LIFECYCLE: LifecycleStage[] = [
  {
    key: "origination",
    label: "Origination",
    blurb: "Deal qualified and won; decision to pursue.",
    isProjectPhase: false,
    deliverables: ["Qualified deal", "Pursue / no-pursue decision"],
    agents: ["—"],
    drilldown: [{ label: "Pipeline", href: "/pipeline" }],
    hitl: [{ label: "Pursue deal", workflows: [], lane: 2, owner: "Owner" }],
  },
  {
    key: "site_control",
    label: "Site Control",
    blurb: "Feasibility assessed; site accepted; project created.",
    isProjectPhase: true,
    deliverables: [
      "Feasibility assessment",
      "Weighted site score + verdict",
      "Drive document intake summary",
    ],
    agents: ["DataSite document analyst", "Site scorer"],
    drilldown: [
      { label: "Site evaluation", href: "/sites" },
      { label: "Project overview", href: "/projects/{id}" },
    ],
    hitl: [
      { label: "Accept feasibility / site score", workflows: ["site_evaluation.accept"], lane: 2, owner: "Owner" },
      { label: "Advance site → project", workflows: ["site_advance.create_project"], lane: 2, owner: "Owner" },
    ],
  },
  {
    key: "permitting",
    label: "Permitting",
    blurb: "Permits tracked; regulatory checklist cleared.",
    isProjectPhase: true,
    deliverables: ["Permit tracker", "Regulatory checklist", "Compliance obligations"],
    agents: ["Compliance monitor"],
    drilldown: [
      { label: "Compliance", href: "/compliance" },
      { label: "Milestones", href: "/projects/{id}" },
    ],
    hitl: [
      { label: "Permit / regulatory sign-off", workflows: ["compliance.permit_signoff"], lane: 2, owner: "Owner" },
    ],
  },
  {
    key: "design",
    label: "Design",
    blurb: "AACE cost classification + cost/schedule package.",
    isProjectPhase: true,
    deliverables: ["AACE cost classification", "Cost + schedule package"],
    agents: ["Design classifier", "Estimator-scheduler"],
    drilldown: [{ label: "Estimates", href: "/estimates" }],
    hitl: [
      { label: "Publish AACE classification", workflows: ["aace_classification.publish"], lane: 2, owner: "Owner" },
      { label: "Publish cost/schedule package", workflows: ["cost_schedule_package.publish"], lane: 2, owner: "Owner" },
    ],
  },
  {
    key: "construction",
    label: "Construction",
    blurb: "Contracts, change orders, procurement, budget & status.",
    isProjectPhase: true,
    deliverables: [
      "Executed contracts",
      "Change orders / purchase orders",
      "Budget vs committed vs forecast",
      "Procurement / long-lead log",
      "Status & risk/issue log",
    ],
    agents: ["Contract extractor", "Contract reviewer", "Contract drafter", "Finance rollup"],
    drilldown: [
      { label: "Contracts", href: "/contracts" },
      { label: "Finance", href: "/finance" },
      { label: "Supply chain", href: "/supply-chain" },
      { label: "Project log", href: "/projects/{id}" },
    ],
    hitl: [
      { label: "Contract extraction", workflows: ["contract_extraction.publish"], lane: 2, owner: "Owner" },
      { label: "Contract review", workflows: ["contract_review.publish"], lane: 2, owner: "Owner" },
      { label: "Contract draft", workflows: ["contract_draft.publish"], lane: 2, owner: "Owner" },
      { label: "Cost commitment / change order", workflows: ["finance.commitment", "finance.change_order"], lane: 3, owner: "Owner + Partner" },
      { label: "External system write (Procore/P6/ACC)", workflows: ["external.write"], lane: 2, owner: "Owner" },
    ],
  },
  {
    key: "commissioning",
    label: "Commissioning",
    blurb: "Commissioning checklist + punch list cleared.",
    isProjectPhase: true,
    deliverables: ["Commissioning checklist", "Punch list", "Readiness sign-off"],
    agents: ["Compliance monitor"],
    drilldown: [
      { label: "Compliance", href: "/compliance" },
      { label: "Milestones", href: "/projects/{id}" },
    ],
    hitl: [
      { label: "Commissioning sign-off", workflows: ["commissioning.signoff"], lane: 2, owner: "Owner" },
    ],
  },
  {
    key: "turnover",
    label: "Turnover",
    blurb: "Handover package; project promoted to operations.",
    isProjectPhase: true,
    deliverables: ["Handover package", "As-builts + O&M docs", "Campus record"],
    agents: ["—"],
    drilldown: [
      { label: "Documents", href: "/documents" },
      { label: "Operations", href: "/operations" },
    ],
    hitl: [
      { label: "Turnover package sign-off", workflows: ["turnover.signoff"], lane: 2, owner: "Owner" },
      { label: "Promote project → Campus", workflows: ["operations.promote_campus"], lane: 2, owner: "Owner" },
    ],
  },
  {
    key: "operations",
    label: "Operations",
    blurb: "Live facility monitoring; incidents; maintenance.",
    isProjectPhase: false,
    deliverables: ["Live monitoring", "Incident records", "Maintenance log"],
    agents: ["Facility monitoring agents", "Incident triage"],
    drilldown: [{ label: "Operations", href: "/operations" }],
    hitl: [
      { label: "Incident escalation (exception-based)", workflows: ["operations.incident_escalation"], lane: 1, owner: "Owner (on flag)" },
    ],
  },
];

/** The 6 code-defined Project.phase values, in order. */
export const PROJECT_PHASES = LIFECYCLE.filter((s) => s.isProjectPhase).map((s) => s.key);

/** Index of a stage key within the full lifecycle (bookends included). */
export function stageIndex(key: string): number {
  return LIFECYCLE.findIndex((s) => s.key === key);
}

/**
 * Map a project's phase to its lifecycle stage index. If the project is
 * complete, callers may treat it as having reached Operations.
 */
export function projectStageIndex(phase: string, status?: string): number {
  if (status === "complete") return stageIndex("operations");
  const idx = stageIndex(phase);
  return idx < 0 ? 1 : idx; // default to site_control if unknown
}

const LANE_LABEL: Record<Lane, string> = {
  1: "Auto",
  2: "Single-sig",
  3: "Dual-sig",
};
export function laneLabel(lane: Lane): string {
  return LANE_LABEL[lane];
}

/** Total distinct HITL gates across the whole lifecycle (for onboarding copy). */
export function totalHitlGates(): number {
  return LIFECYCLE.reduce((n, s) => n + s.hitl.length, 0);
}

/** Substitute {id} in a drilldown href for a concrete project. */
export function resolveHref(href: string, projectId?: string): string {
  return projectId ? href.replace("{id}", projectId) : href.replace("/{id}", "");
}
