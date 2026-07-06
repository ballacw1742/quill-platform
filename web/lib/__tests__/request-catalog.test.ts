import { describe, it, expect } from "vitest";

import {
  buildCatalog,
  filterCatalog,
  chipsForAgent,
  moduleKeyForAgent,
  parseHandledIntents,
  INTENT_EXECUTORS,
  VALID_API_INTENTS,
  type RegistryAgentLike,
} from "@/lib/requests/catalog";
import { MODULE_ROSTER } from "@/lib/modules";

/* ── Fixture: mirrors the 30 agents seeded by api/app/routes/agents.py ── */

const j = (arr: string[]) => JSON.stringify(arr);

const ADK_AGENTS: RegistryAgentLike[] = [
  { agent_id: "quill_coordinator", display_name: "Quill Coordinator", role_summary: "Orchestrator", description: "Routes inbound PMO requests to the right specialist agent.", handled_intents: j(["general", "estimate"]), enabled: true },
  { agent_id: "quill_rfi_triage", display_name: "RFI Triage Agent", role_summary: "RFI Management", description: "Processes Requests for Information.", handled_intents: j(["rfi"]), enabled: true },
  { agent_id: "quill_change_order", display_name: "Change Order Agent", role_summary: "Change Order Processing", description: "Analyzes change orders for cost and schedule impact.", handled_intents: j(["contract"]), enabled: true },
  { agent_id: "quill_schedule_monitor", display_name: "Schedule Monitor", role_summary: "Schedule Analysis", description: "Analyzes project schedules.", handled_intents: j(["schedule"]), enabled: true },
  { agent_id: "quill_status_report", display_name: "Status Report Agent", role_summary: "Reporting", description: "Generates owner-facing project status reports.", handled_intents: j([]), enabled: true },
  { agent_id: "datasite_site_evaluator", display_name: "Site Evaluator", role_summary: "Site Intake & Evaluation", description: "Submits new data center site candidates for Go/No-Go scoring.", handled_intents: j(["site_evaluation"]), enabled: true },
  { agent_id: "datasite_site_researcher", display_name: "Site Researcher", role_summary: "Site Research", description: "Researches utility, fiber, zoning, and incentives.", handled_intents: j(["site_research"]), enabled: true },
  { agent_id: "datasite_site_scorer", display_name: "Site Scorer", role_summary: "Site Scoring", description: "Explains and compares site scores.", handled_intents: j(["site_scoring"]), enabled: true },
  { agent_id: "datasite_site_status", display_name: "Site Status", role_summary: "Pipeline Status", description: "Tracks sites from intake through final verdict.", handled_intents: j(["site_status"]), enabled: true },
  { agent_id: "quill_facility_ops", display_name: "Facility Operations Agent", role_summary: "Facility Operations", description: "Campus status, incidents, PUE, uptime, power metrics.", handled_intents: j(["campus", "incident", "uptime", "pue", "facility", "power", "outage"]), enabled: true },
  { agent_id: "quill_sales", display_name: "Sales & Pipeline Agent", role_summary: "Sales & Pipeline", description: "Deals, accounts, pipeline value, win rates.", handled_intents: j(["deal", "pipeline", "account", "prospect", "won", "lost", "sales", "revenue", "crm"]), enabled: true },
  { agent_id: "quill_customer_success", display_name: "Customer Success Agent", role_summary: "Customer Success", description: "Customer health scores, support tickets, account notes.", handled_intents: j(["customer", "ticket", "support", "health", "churn", "at-risk", "satisfaction", "nps"]), enabled: true },
  { agent_id: "quill_finance", display_name: "Finance Agent", role_summary: "Finance", description: "ARR, invoices, cash position, capex, budget vs actuals.", handled_intents: j(["finance", "invoice", "revenue", "arr", "budget", "cash", "capex", "payment", "overdue"]), enabled: true },
  { agent_id: "quill_intelligence", display_name: "Executive Intelligence Agent", role_summary: "Executive Intelligence", description: "Cross-module executive summaries and KPI rollups.", handled_intents: j(["intelligence", "executive", "summary", "kpi", "dashboard", "briefing", "status", "overview"]), enabled: true },
  { agent_id: "quill_compliance", display_name: "Compliance Agent", role_summary: "Compliance", description: "Compliance checklists, regulatory deadlines, obligations.", handled_intents: j(["compliance", "regulatory", "deadline", "obligation", "checklist", "audit", "permit", "legal"]), enabled: true },
];

const FLEET_AGENTS: RegistryAgentLike[] = [
  { agent_id: "coordinator", display_name: "Fleet Coordinator", role_summary: "Fleet Orchestration", description: "Orchestrates the workflow fleet.", handled_intents: null, enabled: true },
  { agent_id: "rfi-triage", display_name: "RFI Triage", role_summary: "RFI Intake & Routing", description: "Classifies incoming RFIs by discipline and urgency.", handled_intents: null, enabled: true },
  { agent_id: "rfi-drafter", display_name: "RFI Response Drafter", role_summary: "RFI Response Drafting", description: "Drafts RFI responses with citations.", handled_intents: null, enabled: true },
  { agent_id: "submittal-triage", display_name: "Submittal Triage", role_summary: "Submittal Intake & Routing", description: "Logs incoming submittals and routes to reviewers.", handled_intents: null, enabled: true },
  { agent_id: "submittal-spec-validator", display_name: "Submittal Spec Validator", role_summary: "Spec Compliance Checking", description: "Checks submittal contents against the governing spec section.", handled_intents: null, enabled: true },
  { agent_id: "schedule-reader", display_name: "Schedule Reader", role_summary: "Schedule Analysis", description: "Parses project schedules to answer questions.", handled_intents: null, enabled: true },
  { agent_id: "critical-path-watch", display_name: "Critical Path Watch", role_summary: "Critical Path Monitoring", description: "Monitors schedule updates for critical-path changes.", handled_intents: null, enabled: true },
  { agent_id: "dfr-synthesizer", display_name: "Daily Field Report Synthesizer", role_summary: "Field Reporting", description: "Compiles daily field reports from crew notes.", handled_intents: null, enabled: true },
  { agent_id: "safety-aggregator", display_name: "Safety Aggregator", role_summary: "Safety Tracking", description: "Aggregates safety observations and incidents.", handled_intents: null, enabled: true },
  { agent_id: "progress-capture", display_name: "Progress Capture", role_summary: "Progress Tracking", description: "Records installed quantities and percent-complete.", handled_intents: null, enabled: true },
  { agent_id: "co-estimator", display_name: "Change Order Estimator", role_summary: "Change Order Pricing", description: "Prices change orders and drafts the CO package.", handled_intents: null, enabled: true },
  { agent_id: "daily-brief", display_name: "Daily Brief", role_summary: "Daily Briefing", description: "Produces the morning project brief.", handled_intents: null, enabled: true },
  { agent_id: "ccb-prep", display_name: "Change Control Board Prep", role_summary: "CCB Preparation", description: "Prepares Change Control Board packets.", handled_intents: null, enabled: true },
  { agent_id: "owner-reporting", display_name: "Owner Reporting", role_summary: "Owner Communications", description: "Assembles recurring owner reports.", handled_intents: null, enabled: true },
  { agent_id: "procurement-watch", display_name: "Procurement Watch", role_summary: "Procurement Tracking", description: "Tracks procurement and long-lead items.", handled_intents: null, enabled: true },
];

const ALL_30 = [...ADK_AGENTS, ...FLEET_AGENTS];

/* ── parseHandledIntents ───────────────────────────────────────────────── */

describe("parseHandledIntents", () => {
  it("parses a JSON string array", () => {
    expect(parseHandledIntents('["rfi","schedule"]')).toEqual(["rfi", "schedule"]);
  });
  it("returns [] for null/undefined/empty", () => {
    expect(parseHandledIntents(null)).toEqual([]);
    expect(parseHandledIntents(undefined)).toEqual([]);
    expect(parseHandledIntents("")).toEqual([]);
  });
  it("returns [] for invalid JSON or non-arrays", () => {
    expect(parseHandledIntents("not json")).toEqual([]);
    expect(parseHandledIntents('{"a":1}')).toEqual([]);
  });
  it("drops non-string entries", () => {
    expect(parseHandledIntents('["rfi", 42, null, ""]')).toEqual(["rfi"]);
  });
});

/* ── moduleKeyForAgent ─────────────────────────────────────────────────── */

describe("moduleKeyForAgent", () => {
  it("uses the static map for known agents", () => {
    expect(moduleKeyForAgent({ agent_id: "quill_sales" })).toBe("sales");
    expect(moduleKeyForAgent({ agent_id: "procurement-watch" })).toBe("supply-chain");
    expect(moduleKeyForAgent({ agent_id: "ccb-prep" })).toBe("approvals");
    expect(moduleKeyForAgent({ agent_id: "datasite_site_scorer" })).toBe("sites");
  });

  it("infers a module from registry text for unknown agents", () => {
    expect(
      moduleKeyForAgent({
        agent_id: "new_invoice_bot",
        display_name: "Invoice Bot",
        description: "Chases overdue invoices and reconciles payments.",
      }),
    ).toBe("finance");
    expect(
      moduleKeyForAgent({
        agent_id: "new_safety_bot",
        display_name: "Safety Bot",
        description: "Monitors campus incident and uptime reports.",
      }),
    ).toBe("operations");
  });

  it("falls back to the Agents module when nothing matches", () => {
    expect(
      moduleKeyForAgent({ agent_id: "mystery", display_name: "???", description: "" }),
    ).toBe("agents");
  });
});

/* ── chipsForAgent ─────────────────────────────────────────────────────── */

describe("chipsForAgent", () => {
  it("maps handled intents to curated chips and dedupes synonyms", () => {
    const sales = ADK_AGENTS.find((a) => a.agent_id === "quill_sales")!;
    const chips = chipsForAgent(sales);
    // 9 raw intents collapse into 3 curated chips
    const labels = chips.map((c) => c.label);
    expect(labels).toContain("Deal status");
    expect(labels).toContain("Pipeline summary");
    expect(labels).toContain("Flag stalled deals");
    expect(chips.length).toBe(3);
    // Every chip carries a valid explicit API intent
    for (const c of chips) expect(VALID_API_INTENTS.has(c.intent)).toBe(true);
  });

  it("caps chips per agent at 4", () => {
    const compliance = ADK_AGENTS.find((a) => a.agent_id === "quill_compliance")!;
    expect(chipsForAgent(compliance).length).toBeLessThanOrEqual(4);
  });

  it("uses curated fallback chips for intent-less fleet agents", () => {
    const brief = FLEET_AGENTS.find((a) => a.agent_id === "daily-brief")!;
    const chips = chipsForAgent(brief);
    expect(chips).toHaveLength(1);
    expect(chips[0].label).toBe("Morning project brief");
    expect(chips[0].intent).toBe("intelligence");
    expect(chips[0].agentName).toBe("Daily Brief");
  });

  it("generates a chip for a fully unknown agent from registry data", () => {
    const chips = chipsForAgent({
      agent_id: "brand_new_agent",
      display_name: "Brand New Agent",
      role_summary: "Weather Watching",
      description: "Watches weather.",
      handled_intents: null,
    });
    expect(chips).toHaveLength(1);
    expect(chips[0].label).toBe("Weather Watching");
    expect(chips[0].intent).toBe("general");
    expect(chips[0].template.length).toBeGreaterThan(0);
  });

  it("handles unknown intents: humanized label, safe general intent", () => {
    const chips = chipsForAgent({
      agent_id: "x",
      display_name: "X",
      handled_intents: '["weather_alerts"]',
    });
    expect(chips).toHaveLength(1);
    expect(chips[0].label).toBe("Weather alerts");
    expect(chips[0].intent).toBe("general"); // not a valid API intent → general
  });

  it("keeps unknown-to-UI intents that ARE valid API intents explicit", () => {
    const chips = chipsForAgent({
      agent_id: "x2",
      display_name: "X2",
      handled_intents: '["supply_chain"]',
    });
    expect(chips[0].intent).toBe("supply_chain");
  });
});

/* ── buildCatalog ──────────────────────────────────────────────────────── */

describe("executor attribution (G8 honesty)", () => {
  it("every canonical intent has an executor and every executor mapping is a valid intent", () => {
    for (const intent of VALID_API_INTENTS) {
      expect(INTENT_EXECUTORS[intent], `intent ${intent} has no executor`).toBeTruthy();
    }
    for (const intent of Object.keys(INTENT_EXECUTORS)) {
      expect(VALID_API_INTENTS.has(intent)).toBe(true);
    }
  });

  it("ADK agents whose intents route to themselves are direct (no badge)", () => {
    const sales = ADK_AGENTS.find((a) => a.agent_id === "quill_sales")!;
    for (const c of chipsForAgent(sales)) {
      expect(c.direct).toBe(true);
      expect(c.executorAgentId).toBe("quill_sales");
    }
    const rfi = ADK_AGENTS.find((a) => a.agent_id === "quill_rfi_triage")!;
    expect(chipsForAgent(rfi)[0].direct).toBe(true);
  });

  it("fleet-agent chips are marked rerouted with the real executor", () => {
    const drafter = FLEET_AGENTS.find((a) => a.agent_id === "rfi-drafter")!;
    const [chip] = chipsForAgent(drafter);
    expect(chip.direct).toBe(false);
    expect(chip.executorAgentId).toBe("quill_rfi_triage");
    expect(chip.executorAgentName.length).toBeGreaterThan(0);

    const brief = FLEET_AGENTS.find((a) => a.agent_id === "daily-brief")!;
    const [briefChip] = chipsForAgent(brief);
    expect(briefChip.direct).toBe(false);
    expect(briefChip.executorAgentId).toBe("quill_intelligence");
  });

  it("quill_status_report (no dispatchable intent) reroutes to the coordinator", () => {
    const status = ADK_AGENTS.find((a) => a.agent_id === "quill_status_report")!;
    const [chip] = chipsForAgent(status);
    expect(chip.direct).toBe(false);
    expect(chip.executorAgentId).toBe("quill_coordinator");
  });

  it("buildCatalog resolves executor names from the live registry", () => {
    const catalog = buildCatalog(ALL_30);
    const projects = catalog.find((s) => s.module.key === "projects")!;
    const drafterChip = projects.agents
      .find((a) => a.agentId === "rfi-drafter")!
      .chips[0];
    // Registry display_name ("RFI Triage Agent") wins over the static fallback.
    expect(drafterChip.executorAgentName).toBe("RFI Triage Agent");
  });

  it("every chip in the full catalog routes to a known ADK executor", () => {
    const executors = new Set(Object.values(INTENT_EXECUTORS));
    for (const section of buildCatalog(ALL_30)) {
      for (const c of section.chips) {
        expect(executors.has(c.executorAgentId), `chip ${c.id}`).toBe(true);
      }
    }
  });
});

describe("buildCatalog", () => {
  it("returns all 15 module sections in home-grid order", () => {
    const catalog = buildCatalog(ALL_30);
    expect(catalog).toHaveLength(15);
    expect(catalog.map((s) => s.module.label)).toEqual(MODULE_ROSTER.map((m) => m.label));
  });

  it("with the full seeded registry, every module has at least one chip", () => {
    const catalog = buildCatalog(ALL_30);
    for (const section of catalog) {
      expect(section.chips.length, `module ${section.module.label} has no chips`).toBeGreaterThan(0);
    }
  });

  it("all 30 seeded agents land in a section", () => {
    const catalog = buildCatalog(ALL_30);
    const placed = catalog.flatMap((s) => s.agents.map((a) => a.agentId)).sort();
    expect(placed).toEqual(ALL_30.map((a) => a.agent_id).sort());
  });

  it("every chip's intent is valid for POST /v1/requests", () => {
    const catalog = buildCatalog(ALL_30);
    for (const section of catalog) {
      for (const c of section.chips) {
        expect(VALID_API_INTENTS.has(c.intent), `chip ${c.id} intent=${c.intent}`).toBe(true);
      }
    }
  });

  it("skips disabled agents", () => {
    const catalog = buildCatalog([
      { agent_id: "quill_sales", display_name: "Sales", handled_intents: '["deal"]', enabled: false },
    ]);
    const sales = catalog.find((s) => s.module.key === "sales")!;
    expect(sales.agents).toHaveLength(0);
    expect(sales.chips).toHaveLength(0);
  });

  it("dedupes identical chip labels within a section", () => {
    const catalog = buildCatalog([
      { agent_id: "a1", display_name: "Agent One", description: "invoice bot", handled_intents: '["invoice"]', enabled: true },
      { agent_id: "a2", display_name: "Agent Two", description: "payments bot invoice", handled_intents: '["payment"]', enabled: true },
    ]);
    const finance = catalog.find((s) => s.module.key === "finance")!;
    // invoice + payment map to the same "Overdue invoices" chip
    const labels = finance.chips.map((c) => c.label);
    expect(labels.filter((l) => l === "Overdue invoices")).toHaveLength(1);
  });

  it("returns empty sections (not missing sections) when the registry is empty", () => {
    const catalog = buildCatalog([]);
    expect(catalog).toHaveLength(15);
    expect(catalog.every((s) => s.agents.length === 0)).toBe(true);
  });
});

/* ── filterCatalog ─────────────────────────────────────────────────────── */

describe("filterCatalog", () => {
  const catalog = buildCatalog(ALL_30);

  it("returns the catalog unchanged for an empty/whitespace query", () => {
    expect(filterCatalog(catalog, "")).toBe(catalog);
    expect(filterCatalog(catalog, "   ")).toBe(catalog);
  });

  it("matches module names (whole section kept)", () => {
    const out = filterCatalog(catalog, "Finance");
    expect(out.some((s) => s.module.key === "finance")).toBe(true);
    const fin = out.find((s) => s.module.key === "finance")!;
    const full = catalog.find((s) => s.module.key === "finance")!;
    expect(fin.chips.length).toBe(full.chips.length);
  });

  it("matches agent display names", () => {
    const out = filterCatalog(catalog, "Procurement Watch");
    expect(out).toHaveLength(1);
    expect(out[0].module.key).toBe("supply-chain");
    expect(out[0].agents.map((a) => a.agentId)).toEqual(["procurement-watch"]);
  });

  it("matches agent descriptions", () => {
    const out = filterCatalog(catalog, "crew notes");
    expect(out.some((s) => s.agents.some((a) => a.agentId === "dfr-synthesizer"))).toBe(true);
  });

  it("matches chip labels", () => {
    const out = filterCatalog(catalog, "stalled");
    const sales = out.find((s) => s.module.key === "sales");
    expect(sales).toBeDefined();
    expect(sales!.agents.some((a) => a.agentId === "quill_sales")).toBe(true);
  });

  it("is case-insensitive", () => {
    expect(filterCatalog(catalog, "COMPLIANCE").length).toBeGreaterThan(0);
  });

  it("drops non-matching and empty sections when searching", () => {
    const out = filterCatalog(catalog, "zzz-no-such-thing");
    expect(out).toHaveLength(0);
  });
});
