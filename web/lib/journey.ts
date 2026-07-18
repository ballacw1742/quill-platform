/**
 * Journey mapping — derives the 5-phase lifecycle view from existing
 * project data. Purely presentational; no schema changes.
 *
 * Phases: Site → Estimate → Contract → Project → Operate.
 * Each phase has ordered steps, expected deliverables, and the agents
 * that participate in that step.
 *
 * Ported 2026-07-18 from the Lovable redesign (quill-platform-builder
 * src/lib/quill/journey.ts). Repointed to prod's `@/lib/schemas` types and
 * to Next.js href strings (no TanStack `$param` route templates).
 */

import type { QuillProject } from "@/lib/schemas";

/** Prod's ProjectSchema.phase is z.string(); the lifecycle enum used here. */
export type ProjectPhase =
  | "site_control"
  | "permitting"
  | "design"
  | "construction"
  | "commissioning"
  | "turnover";

export type JourneyPhaseKey = "site" | "estimate" | "contract" | "project" | "operate";

export type StepStatus = "complete" | "current" | "upcoming";
export type PhaseStatus = "complete" | "current" | "upcoming";

export interface DeliverableTarget {
  /** Next.js href for <Link href=...>. Query encoded inline. */
  href: string;
}

export interface JourneyStep {
  key: string;
  label: string;
  description: string;
  /** Module route the deliverable lives in. */
  moduleRoute:
    | "/sites"
    | "/estimates"
    | "/contracts"
    | "/projects"
    | "/operations"
    | "/queue"
    | "/requests";
  /** Which agents are involved in this step. */
  agents: string[];
  /** Intent chip for the step-scoped chat composer. */
  intent: string;
  /** What the step produces. */
  deliverable: string;
  /**
   * Where a tap on this step's deliverable card should actually go —
   * resolved from the project so we can target the right project detail
   * page or a filtered documents view. Returns a Next.js href.
   */
  target: (project: Pick<QuillProject, "id">) => DeliverableTarget;
}

export interface JourneyPhase {
  key: JourneyPhaseKey;
  label: string;
  tagline: string;
  /** Tailwind gradient token for iOS-tinted card. */
  tint: string;
  steps: JourneyStep[];
}

/** Small helper: build a Next.js href with an encoded query string. */
function href(path: string, query?: Record<string, string>): DeliverableTarget {
  if (!query || Object.keys(query).length === 0) return { href: path };
  const qs = new URLSearchParams(query).toString();
  return { href: `${path}?${qs}` };
}

export const JOURNEY: JourneyPhase[] = [
  {
    key: "site",
    label: "Site",
    tagline: "Find, score, and decide on the site.",
    tint: "from-stone-300/20 to-stone-500/5",
    steps: [
      {
        key: "research",
        label: "Site research",
        description: "Assemble candidate parcels, zoning, fiber, and power context.",
        moduleRoute: "/sites",
        agents: ["site-researcher", "coordinator"],
        intent: "site_research",
        deliverable: "Datasite report",
        target: (p) => href("/documents", { project: p.id, tag: "site-research" }),
      },
      {
        key: "evaluate",
        label: "Evaluate",
        description: "Score sites across power, water, zoning, and community risk.",
        moduleRoute: "/sites",
        agents: ["site-evaluator", "site-scorer"],
        intent: "site_scoring",
        deliverable: "Site scorecard",
        target: (p) => href("/sites", { project: p.id, section: "scorecard" }),
      },
      {
        key: "decide",
        label: "Go / no-go",
        description: "Verdict memo and commitment to advance the site.",
        moduleRoute: "/sites",
        agents: ["coordinator", "site-status"],
        intent: "site_status",
        deliverable: "Go/no-go memo",
        target: (p) => href("/documents", { project: p.id, tag: "go-no-go" }),
      },
    ],
  },
  {
    key: "estimate",
    label: "Estimate",
    tagline: "Build the cost picture that unlocks contracting.",
    tint: "from-stone-300/20 to-stone-500/5",
    steps: [
      {
        key: "takeoff",
        label: "Takeoff & unit rates",
        description: "Quantities, unit rates, and design assumptions.",
        moduleRoute: "/estimates",
        agents: ["cost-estimator", "coordinator"],
        intent: "cost_takeoff",
        deliverable: "Takeoff sheet",
        target: (p) => href("/documents", { project: p.id, tag: "takeoff" }),
      },
      {
        key: "estimate",
        label: "Estimate package",
        description: "Full cost estimate ready for owner review.",
        moduleRoute: "/estimates",
        agents: ["cost-estimator"],
        intent: "estimate_package",
        deliverable: "Estimate v1",
        target: (p) => href("/estimates", { project: p.id }),
      },
    ],
  },
  {
    key: "contract",
    label: "Contract",
    tagline: "Draft, review, and execute the agreement.",
    tint: "from-stone-300/20 to-stone-500/5",
    steps: [
      {
        key: "draft",
        label: "Draft",
        description: "Initial contract draft from approved estimate.",
        moduleRoute: "/contracts",
        agents: ["contract-reviewer", "coordinator"],
        intent: "contract_draft",
        deliverable: "Contract draft",
        target: (p) => href("/contracts", { project: p.id, stage: "draft" }),
      },
      {
        key: "review",
        label: "Review & redline",
        description: "Clause-by-clause review with counterparty markup.",
        moduleRoute: "/contracts",
        agents: ["contract-reviewer"],
        intent: "contract_review",
        deliverable: "Redlined contract",
        target: (p) => href("/contracts", { project: p.id, stage: "redline" }),
      },
      {
        key: "execute",
        label: "Execute",
        description: "Signatures collected, contract counter-signed.",
        moduleRoute: "/contracts",
        agents: ["coordinator"],
        intent: "contract_execute",
        deliverable: "Executed contract",
        target: (p) => href("/contracts", { project: p.id, stage: "executed" }),
      },
    ],
  },
  {
    key: "project",
    label: "Project",
    tagline: "Schedule, RFIs, change orders, and progress.",
    tint: "from-stone-300/20 to-stone-500/5",
    steps: [
      {
        key: "schedule",
        label: "Schedule",
        description: "Critical-path schedule with milestones.",
        moduleRoute: "/projects",
        agents: ["schedule-builder"],
        intent: "schedule_build",
        deliverable: "Baseline schedule",
        target: (p) => href(`/projects/${p.id}`, { tab: "milestones" }),
      },
      {
        key: "rfis",
        label: "RFIs",
        description: "Field RFIs answered and routed to the right discipline.",
        moduleRoute: "/projects",
        agents: ["rfi-manager"],
        intent: "rfi_management",
        deliverable: "RFI log",
        target: (p) => href(`/projects/${p.id}`, { tab: "log" }),
      },
      {
        key: "changes",
        label: "Change orders",
        description: "Cost & schedule impact of design changes.",
        moduleRoute: "/projects",
        agents: ["change-order"],
        intent: "change_order",
        deliverable: "Change-order package",
        target: (p) => href(`/projects/${p.id}`, { tab: "deliverables" }),
      },
      {
        key: "progress",
        label: "Progress",
        description: "Field reports rolled up into weekly progress.",
        moduleRoute: "/projects",
        agents: ["progress-tracker"],
        intent: "progress_report",
        deliverable: "Progress summary",
        target: (p) => href("/documents", { project: p.id, type: "status_update" }),
      },
    ],
  },
  {
    key: "operate",
    label: "Operate",
    tagline: "Commission, run, and report on the asset.",
    tint: "from-stone-300/20 to-stone-500/5",
    steps: [
      {
        key: "commission",
        label: "Commissioning",
        description: "IST cycles, level 4 & 5 sign-off.",
        moduleRoute: "/operations",
        agents: ["coordinator", "progress-tracker"],
        intent: "commissioning",
        deliverable: "IST results",
        target: (p) => href("/operations", { project: p.id, section: "commissioning" }),
      },
      {
        key: "reporting",
        label: "Owner reporting",
        description: "Owner-facing status reports from live operations data.",
        moduleRoute: "/operations",
        agents: ["owner-reporting"],
        intent: "owner_reporting",
        deliverable: "Owner report",
        target: (p) => href("/documents", { project: p.id, type: "comms_draft" }),
      },
      {
        key: "uptime",
        label: "Uptime & incidents",
        description: "Uptime, PUE, and incident response.",
        moduleRoute: "/operations",
        agents: ["safety-aggregator", "coordinator"],
        intent: "operations_status",
        deliverable: "Operations rollup",
        target: (p) => href("/operations", { project: p.id, section: "uptime" }),
      },
    ],
  },
];

export function findPhase(key: JourneyPhaseKey): JourneyPhase {
  const p = JOURNEY.find((x) => x.key === key);
  if (!p) throw new Error(`Unknown journey phase: ${key}`);
  return p;
}

/**
 * Which journey phase a project is currently in, given its ProjectPhase.
 */
export function currentJourneyPhase(
  p: Pick<QuillProject, "phase" | "committed_usd">,
): JourneyPhaseKey {
  const phase = p.phase as ProjectPhase;
  if (phase === "site_control") return "site";
  if (phase === "permitting" || phase === "design") {
    return (p.committed_usd ?? 0) > 0 ? "contract" : "estimate";
  }
  if (phase === "construction") return "project";
  return "operate"; // commissioning + turnover
}

/**
 * Overall phase status for the journey rail. Completed phases stay
 * tappable but render muted.
 */
export function phaseStatus(
  phase: JourneyPhaseKey,
  project: Pick<QuillProject, "phase" | "committed_usd">,
): PhaseStatus {
  const order: JourneyPhaseKey[] = ["site", "estimate", "contract", "project", "operate"];
  const currentIdx = order.indexOf(currentJourneyPhase(project));
  const idx = order.indexOf(phase);
  if (idx < currentIdx) return "complete";
  if (idx === currentIdx) return "current";
  return "upcoming";
}

/**
 * Step status within a phase. Uses milestone counts as a soft proxy for
 * how far the current phase has progressed; completed/upcoming phases
 * are all-complete / all-upcoming respectively.
 */
export function stepStatus(
  phase: JourneyPhaseKey,
  stepIndex: number,
  project: Pick<
    QuillProject,
    "phase" | "committed_usd" | "milestone_complete" | "milestone_total"
  >,
): StepStatus {
  const status = phaseStatus(phase, project);
  if (status === "complete") return "complete";
  if (status === "upcoming") return "upcoming";

  const steps = findPhase(phase).steps;
  const denom = Math.max(project.milestone_total || 0, steps.length);
  const raw = (project.milestone_complete || 0) / (denom || 1);
  const progressedTo = Math.floor(raw * steps.length);
  const current = Math.max(0, Math.min(steps.length - 1, progressedTo));

  if (stepIndex < current) return "complete";
  if (stepIndex === current) return "current";
  return "upcoming";
}

/** Progress ratio [0..1] for the phase pill on the home rail. */
export function phaseProgress(
  phase: JourneyPhaseKey,
  project: Pick<
    QuillProject,
    "phase" | "committed_usd" | "milestone_complete" | "milestone_total"
  >,
): number {
  const status = phaseStatus(phase, project);
  if (status === "complete") return 1;
  if (status === "upcoming") return 0;
  const denom = project.milestone_total || 1;
  return Math.min(1, (project.milestone_complete || 0) / denom);
}
