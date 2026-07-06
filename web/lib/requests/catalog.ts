/**
 * Requests action catalog — Phase 3 of the UI redesign
 * (docs/UI_REDESIGN_BRIEF.md §5).
 *
 * Turns the live agent registry (GET /v1/agents) into a catalog of tappable
 * action chips grouped by the 15 home-screen modules, so all registered
 * agents are reachable from the Requests hub and newly registered agents
 * appear automatically.
 *
 * Sourcing split (per sprint brief):
 *   - The AGENT LIST is always the API — nothing renders for an agent that
 *     isn't in the registry response.
 *   - Thin static maps translate raw registry data into human UI:
 *       AGENT_MODULE_MAP   agent_id → module key (semantic grouping)
 *       INTENT_CHIPS       handled_intent → human chip label + prompt template
 *       AGENT_FALLBACK_CHIPS  curated chips for agents whose registry rows
 *                             have no mappable handled_intents (workflow fleet)
 *   - Unknown agents (none of the above) still get a generated chip from
 *     their registry display_name / role_summary, and a module inferred from
 *     keyword matching — so new registrations show up with zero code changes.
 *
 * Pure logic — no React/DOM — so it is unit-testable under the node env.
 */

import { MODULE_ROSTER, type ModuleDef } from "@/lib/modules";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Structural subset of lib/schemas.ts Agent that the catalog needs. */
export interface RegistryAgentLike {
  agent_id: string;
  display_name?: string | null;
  description?: string | null;
  role_summary?: string | null;
  /** JSON array serialized as text, e.g. '["rfi","schedule"]'. */
  handled_intents?: string | null;
  enabled?: boolean | null;
}

export interface CatalogChip {
  /** Unique within the catalog: `${agentId}:${chipKey}`. */
  id: string;
  /** Human action label, e.g. "Draft an RFI". Never truncated in UI. */
  label: string;
  /** Prompt template that pre-fills the composer (user edits before send). */
  template: string;
  /**
   * Explicit intent sent with POST /v1/requests (must be in the backend's
   * _VALID_INTENTS). "general" lets the coordinator auto-classify.
   */
  intent: string;
  agentId: string;
  agentName: string;
  /**
   * Sprint 5.5 (G8) — honesty: agent_id of the ADK agent that will ACTUALLY
   * execute this chip's intent (mirror of the API's INTENT_TO_ADK_AGENT).
   * Workflow-fleet agents are runtime daemons — they are not invocable via
   * POST /v1/requests, so their chips reroute to the intent's ADK executor.
   */
  executorAgentId: string;
  /** Human display name for the executor (registry name when available). */
  executorAgentName: string;
  /** True when the badged agent is the one that actually runs the request. */
  direct: boolean;
}

export interface CatalogAgent {
  agentId: string;
  name: string;
  description: string;
  roleSummary: string;
  chips: CatalogChip[];
}

export interface CatalogSection {
  module: ModuleDef;
  agents: CatalogAgent[];
  /** All chips of the section's agents, deduped by label. */
  chips: CatalogChip[];
}

// ---------------------------------------------------------------------------
// Static map 1 — agent → module (thin, semantic; fallback = keyword inference)
// ---------------------------------------------------------------------------

export const AGENT_MODULE_MAP: Record<string, string> = {
  // ADK agents (seeded by api/app/routes/agents.py SEED_AGENTS)
  quill_coordinator: "requests",
  quill_rfi_triage: "projects",
  quill_change_order: "contracts",
  quill_schedule_monitor: "projects",
  quill_status_report: "projects",
  datasite_site_evaluator: "sites",
  datasite_site_researcher: "sites",
  datasite_site_scorer: "sites",
  datasite_site_status: "sites",
  quill_facility_ops: "operations",
  quill_sales: "sales",
  quill_customer_success: "customers",
  quill_finance: "finance",
  quill_intelligence: "intelligence",
  quill_compliance: "compliance",
  // Workflow fleet (AGENT_FLEET slugs)
  coordinator: "agents",
  "rfi-triage": "projects",
  "rfi-drafter": "projects",
  "submittal-triage": "documents",
  "submittal-spec-validator": "documents",
  "schedule-reader": "projects",
  "critical-path-watch": "projects",
  "dfr-synthesizer": "operations",
  "safety-aggregator": "operations",
  "progress-capture": "operations",
  "co-estimator": "estimates",
  "daily-brief": "intelligence",
  "ccb-prep": "approvals",
  "owner-reporting": "projects",
  "procurement-watch": "supply-chain",
};

// ---------------------------------------------------------------------------
// Static map 2 — handled_intent → chip (label + template + API intent)
// ---------------------------------------------------------------------------

/** Mirrors _VALID_INTENTS in api/app/routes/requests.py submit_request. */
export const VALID_API_INTENTS = new Set([
  "estimate", "schedule", "rfi", "contract", "general",
  "site_evaluation", "site_research", "site_scoring", "site_status",
  "facility_ops", "sales", "customer_success", "finance",
  "intelligence", "compliance", "supply_chain",
]);

/**
 * Sprint 5.5 (G8) — mirror of INTENT_TO_ADK_AGENT in
 * api/app/routes/requests.py: which ADK agent actually executes each
 * canonical intent when POST /v1/requests dispatches. Keep in sync.
 */
export const INTENT_EXECUTORS: Record<string, string> = {
  estimate: "quill_coordinator",
  schedule: "quill_schedule_monitor",
  rfi: "quill_rfi_triage",
  contract: "quill_change_order",
  general: "quill_coordinator",
  site_evaluation: "datasite_site_evaluator",
  site_research: "datasite_site_researcher",
  site_scoring: "datasite_site_scorer",
  site_status: "datasite_site_status",
  facility_ops: "quill_facility_ops",
  sales: "quill_sales",
  customer_success: "quill_customer_success",
  supply_chain: "quill_supply_chain",
  finance: "quill_finance",
  intelligence: "quill_intelligence",
  compliance: "quill_compliance",
};

/** Executor display names used when the registry row isn't in the payload. */
const EXECUTOR_FALLBACK_NAMES: Record<string, string> = {
  quill_coordinator: "Quill Coordinator",
  quill_schedule_monitor: "Schedule Monitor",
  quill_rfi_triage: "RFI Triage Agent",
  quill_change_order: "Change Order Agent",
  datasite_site_evaluator: "Site Evaluator",
  datasite_site_researcher: "Site Researcher",
  datasite_site_scorer: "Site Scorer",
  datasite_site_status: "Site Status",
  quill_facility_ops: "Facility Operations Agent",
  quill_sales: "Sales & Pipeline Agent",
  quill_customer_success: "Customer Success Agent",
  quill_supply_chain: "Supply Chain Agent",
  quill_finance: "Finance Agent",
  quill_intelligence: "Executive Intelligence Agent",
  quill_compliance: "Compliance Agent",
};

interface ChipDef {
  /** Dedupe key — several raw intents can map to the same chip. */
  key: string;
  label: string;
  template: string;
  intent: string;
}

const chip = (key: string, label: string, template: string, intent: string): ChipDef => ({
  key,
  label,
  template,
  intent,
});

/**
 * Raw registry intents → curated chips. Synonym intents point at the same
 * chip key so an agent advertising ["deal","account","crm"] renders one
 * "Deal status" chip, not three near-duplicates.
 */
export const INTENT_CHIPS: Record<string, ChipDef> = (() => {
  const defs: Record<string, ChipDef> = {};
  const add = (intents: string[], c: ChipDef) => {
    for (const i of intents) defs[i] = c;
  };

  // PMO core
  add(["general"], chip("ask", "Ask anything", "I need help with ", "general"));
  add(["estimate"], chip("estimate", "Get a cost estimate", "Estimate the cost for ", "estimate"));
  add(["schedule"], chip("schedule", "Build a schedule", "Build a schedule for ", "schedule"));
  add(["rfi"], chip("rfi", "Draft an RFI", "Draft an RFI about ", "rfi"));
  add(["contract"], chip("contract", "Analyze a change order", "Analyze the cost and schedule impact of this change order: ", "contract"));

  // DataSite
  add(["site_evaluation"], chip("site-eval", "Evaluate a new site", "Evaluate this site for data center development: ", "site_evaluation"));
  add(["site_research"], chip("site-research", "Research a site", "Research utility capacity, fiber, and zoning near ", "site_research"));
  add(["site_scoring"], chip("site-score", "Explain a site score", "Explain the score for site ", "site_scoring"));
  add(["site_status"], chip("site-status", "Check site pipeline status", "What's the status of the site evaluation for ", "site_status"));

  // Facility operations
  add(["campus", "facility"], chip("campus", "Campus status", "Give me the current campus status overview", "facility_ops"));
  add(["incident", "outage"], chip("incident", "Active incidents", "Show active P1/P2 incidents across our campuses", "facility_ops"));
  add(["uptime"], chip("uptime", "Uptime report", "What's our uptime across campuses this month?", "facility_ops"));
  add(["pue"], chip("pue", "PUE metrics", "What are the latest PUE numbers by campus?", "facility_ops"));
  add(["power"], chip("power", "Power metrics", "Summarize current power utilization across campuses", "facility_ops"));

  // Sales & pipeline
  add(["deal", "account", "crm"], chip("deal", "Deal status", "Summarize the status of our active deals", "sales"));
  add(["pipeline", "prospect", "sales", "revenue"], chip("pipeline", "Pipeline summary", "What's our total pipeline value and win rate?", "sales"));
  add(["won", "lost"], chip("stalled", "Flag stalled deals", "Flag stalled or at-risk deals in the pipeline", "sales"));

  // Customer success
  add(["customer", "health", "satisfaction", "nps"], chip("cust-health", "Customer health", "Show customer health scores and flag at-risk customers", "customer_success"));
  add(["ticket", "support"], chip("tickets", "Open tickets", "Show open P1/P2 support tickets", "customer_success"));
  add(["churn", "at-risk"], chip("churn", "At-risk customers", "Which customers are at risk of churn?", "customer_success"));

  // Supply chain
  add(["supply_chain", "equipment", "vendor"], chip("equipment", "Equipment status", "Show equipment orders and flag at-risk deliveries", "supply_chain"));
  add(["procurement", "lead_time", "delivery"], chip("leadtime", "Lead-time risk", "Which long-lead items are at risk against required-on-site dates?", "supply_chain"));

  // Finance
  add(["finance", "budget"], chip("budget", "Budget vs actuals", "Show budget vs actuals and flag variances", "finance"));
  add(["invoice", "overdue", "payment"], chip("invoices", "Overdue invoices", "List overdue invoices and amounts outstanding", "finance"));
  add(["arr"], chip("arr", "ARR summary", "What's our current ARR and how has it trended?", "finance"));
  add(["cash", "capex"], chip("cash", "Cash & capex", "Summarize our cash position and capex commitments", "finance"));

  // Executive intelligence
  add(["intelligence", "executive", "summary", "overview", "status"], chip("exec", "Executive summary", "Give me an executive summary of business health across all modules", "intelligence"));
  add(["kpi", "dashboard"], chip("kpi", "KPI rollup", "Show the KPI rollup across Operations, Sales, Finance, and Customer Success", "intelligence"));
  add(["briefing", "brief"], chip("brief", "Daily briefing", "Give me today's briefing: overnight developments, priorities, and risks", "intelligence"));

  // Compliance
  add(["compliance", "checklist"], chip("comp-check", "Compliance checklist", "Show the compliance checklist and flag overdue items", "compliance"));
  add(["regulatory", "deadline", "permit", "filing"], chip("comp-deadlines", "Regulatory deadlines", "What regulatory deadlines are coming up in the next 90 days?", "compliance"));
  add(["obligation", "legal"], chip("comp-obligations", "Contract obligations", "List contract obligations that are overdue or at risk", "compliance"));
  add(["audit"], chip("comp-audit", "Audit readiness", "Summarize our audit readiness and open compliance gaps", "compliance"));

  return defs;
})();

// ---------------------------------------------------------------------------
// Static map 3 — curated chips for agents with no mappable handled_intents
// (the 15 workflow-fleet agents + quill_status_report advertise none).
// ---------------------------------------------------------------------------

export const AGENT_FALLBACK_CHIPS: Record<string, ChipDef[]> = {
  quill_status_report: [
    chip("owner-status", "Owner status report", "Generate an owner-facing status report for ", "general"),
  ],
  coordinator: [
    chip("fleet-route", "Route work to the fleet", "Coordinate this task across the agent fleet: ", "general"),
  ],
  "rfi-triage": [
    chip("rfi-triage", "Triage an RFI", "Triage this RFI and route it to the right reviewer: ", "rfi"),
  ],
  "rfi-drafter": [
    chip("rfi-draft", "Draft an RFI response", "Draft a response to this RFI with citations: ", "rfi"),
  ],
  "submittal-triage": [
    chip("submittal-log", "Log a submittal", "Log this submittal and route it to the responsible reviewer: ", "general"),
  ],
  "submittal-spec-validator": [
    chip("submittal-check", "Check a submittal against spec", "Check this submittal against the governing spec section: ", "general"),
  ],
  "schedule-reader": [
    chip("schedule-query", "Query the schedule", "From the project schedule, show me ", "schedule"),
  ],
  "critical-path-watch": [
    chip("cp-watch", "Critical path check", "Check the schedule for critical-path changes and float erosion", "schedule"),
  ],
  "dfr-synthesizer": [
    chip("dfr", "Compile a daily field report", "Compile a daily field report from these crew notes: ", "general"),
  ],
  "safety-aggregator": [
    chip("safety", "Safety trends", "Summarize recent safety observations and recurring hazards", "general"),
  ],
  "progress-capture": [
    chip("progress", "Record progress", "Record installed quantities and percent complete: ", "general"),
  ],
  "co-estimator": [
    chip("co-price", "Price a change order", "Price this change order and build the cost breakdown: ", "estimate"),
  ],
  "daily-brief": [
    chip("morning-brief", "Morning project brief", "Generate the morning project brief", "intelligence"),
  ],
  "ccb-prep": [
    chip("ccb", "Prep a CCB packet", "Prepare the Change Control Board packet for pending change orders", "general"),
  ],
  "owner-reporting": [
    chip("owner-report", "Assemble an owner report", "Assemble this month's owner report: progress, budget, schedule, open issues", "general"),
  ],
  "procurement-watch": [
    chip("procurement", "Long-lead item risk", "Which long-lead procurement items are at risk against required-on-site dates?", "supply_chain"),
  ],
};

/** Max chips rendered per agent — keeps sections scannable. */
const MAX_CHIPS_PER_AGENT = 4;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function parseHandledIntents(raw: string | null | undefined): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x): x is string => typeof x === "string" && x.length > 0);
  } catch {
    return [];
  }
}

function agentText(agent: RegistryAgentLike): string {
  return [
    agent.display_name ?? "",
    agent.role_summary ?? "",
    agent.description ?? "",
    parseHandledIntents(agent.handled_intents).join(" "),
  ]
    .join(" ")
    .toLowerCase();
}

/**
 * Module for an agent: static map first, then keyword inference over
 * registry text, then the Agents module as the final home.
 */
export function moduleKeyForAgent(agent: RegistryAgentLike): string {
  const mapped = AGENT_MODULE_MAP[agent.agent_id];
  if (mapped) return mapped;

  const text = agentText(agent);
  let bestKey = "agents";
  let bestScore = 0;
  for (const mod of MODULE_ROSTER) {
    let score = 0;
    for (const kw of mod.keywords) {
      if (text.includes(kw)) score += 1;
    }
    if (score > bestScore) {
      bestScore = score;
      bestKey = mod.key;
    }
  }
  return bestKey;
}

function humanizeIntent(intent: string): string {
  const words = intent.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Chips for one agent:
 *   1. curated per-intent chips from handled_intents (deduped by chip key)
 *   2. curated fallback chips for known intent-less agents
 *   3. generated chip from registry display data (unknown agents)
 */
export function chipsForAgent(agent: RegistryAgentLike): CatalogChip[] {
  const name = agent.display_name || agent.agent_id;
  const defs: ChipDef[] = [];
  const seen = new Set<string>();

  for (const intent of parseHandledIntents(agent.handled_intents)) {
    const def =
      INTENT_CHIPS[intent] ??
      // Unknown intent from a newly registered agent — generate a chip.
      chip(
        `raw-${intent}`,
        humanizeIntent(intent),
        `Help me with ${humanizeIntent(intent).toLowerCase()}: `,
        VALID_API_INTENTS.has(intent) ? intent : "general",
      );
    if (!seen.has(def.key)) {
      seen.add(def.key);
      defs.push(def);
    }
  }

  if (defs.length === 0) {
    const fallback = AGENT_FALLBACK_CHIPS[agent.agent_id];
    if (fallback) {
      defs.push(...fallback);
    } else {
      // Fully unknown agent — still reachable via a generated chip.
      const label = agent.role_summary || name;
      defs.push(
        chip(
          "generated",
          label,
          `${name}, help me with ${(agent.role_summary || "this").toLowerCase()}: `,
          "general",
        ),
      );
    }
  }

  return defs.slice(0, MAX_CHIPS_PER_AGENT).map((d) => {
    const executorAgentId = INTENT_EXECUTORS[d.intent] ?? INTENT_EXECUTORS.general;
    return {
      id: `${agent.agent_id}:${d.key}`,
      label: d.label,
      template: d.template,
      intent: d.intent,
      agentId: agent.agent_id,
      agentName: name,
      executorAgentId,
      executorAgentName:
        EXECUTOR_FALLBACK_NAMES[executorAgentId] ?? humanizeIntent(executorAgentId),
      direct: executorAgentId === agent.agent_id,
    };
  });
}

// ---------------------------------------------------------------------------
// Catalog build + filter
// ---------------------------------------------------------------------------

/**
 * Build the full catalog: one section per module, all 15, home-grid order.
 * Disabled agents are skipped (their actions would silently no-op).
 */
export function buildCatalog(agents: RegistryAgentLike[]): CatalogSection[] {
  const byModule = new Map<string, CatalogAgent[]>();

  // Registry display names for executor attribution (G8 honesty badges).
  const nameById = new Map<string, string>();
  for (const agent of agents) {
    if (agent.display_name) nameById.set(agent.agent_id, agent.display_name);
  }

  for (const agent of agents) {
    if (agent.enabled === false) continue;
    const key = moduleKeyForAgent(agent);
    const entry: CatalogAgent = {
      agentId: agent.agent_id,
      name: agent.display_name || agent.agent_id,
      description: agent.description ?? "",
      roleSummary: agent.role_summary ?? "",
      chips: chipsForAgent(agent).map((c) => ({
        ...c,
        executorAgentName: nameById.get(c.executorAgentId) ?? c.executorAgentName,
      })),
    };
    const list = byModule.get(key) ?? [];
    list.push(entry);
    byModule.set(key, list);
  }

  return MODULE_ROSTER.map((module) => {
    const sectionAgents = (byModule.get(module.key) ?? []).sort((a, b) =>
      a.name.localeCompare(b.name),
    );
    // Flatten chips, dedupe near-identical labels across agents in a section.
    const chips: CatalogChip[] = [];
    const seenLabels = new Set<string>();
    for (const a of sectionAgents) {
      for (const c of a.chips) {
        const norm = c.label.toLowerCase();
        if (seenLabels.has(norm)) continue;
        seenLabels.add(norm);
        chips.push(c);
      }
    }
    return { module, agents: sectionAgents, chips };
  });
}

/**
 * Case-insensitive keyword filter across module names/keywords, agent names,
 * role summaries, descriptions, and chip labels.
 *
 * - Empty/whitespace query → the catalog unchanged (all 15 sections).
 * - Module match → the whole section stays.
 * - Agent match → section stays with only matching agents' chips.
 * - Chip-label match → that agent (and its chips) stays.
 * - Non-empty query drops sections with no matches (incl. empty modules).
 */
export function filterCatalog(sections: CatalogSection[], query: string): CatalogSection[] {
  const q = query.trim().toLowerCase();
  if (!q) return sections;

  const out: CatalogSection[] = [];
  for (const section of sections) {
    const moduleMatch =
      section.module.label.toLowerCase().includes(q) ||
      section.module.keywords.some((kw) => kw.includes(q) || q.includes(kw));

    if (moduleMatch && section.agents.length > 0) {
      out.push(section);
      continue;
    }

    const agents = section.agents.filter((a) => {
      const hay = `${a.name} ${a.roleSummary} ${a.description}`.toLowerCase();
      if (hay.includes(q)) return true;
      return a.chips.some((c) => c.label.toLowerCase().includes(q) || c.template.toLowerCase().includes(q));
    });
    if (agents.length === 0) continue;

    const chips: CatalogChip[] = [];
    const seenLabels = new Set<string>();
    for (const a of agents) {
      for (const c of a.chips) {
        const norm = c.label.toLowerCase();
        if (seenLabels.has(norm)) continue;
        seenLabels.add(norm);
        chips.push(c);
      }
    }
    out.push({ module: section.module, agents, chips });
  }
  return out;
}
