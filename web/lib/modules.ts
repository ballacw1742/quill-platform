/**
 * Shared module roster — the 15 home-screen modules, order/names/gradients
 * locked by UI_REDESIGN_BRIEF §3 + §9.1.
 *
 * Single source of truth used by:
 *   - the home grid (app/page.tsx) — icons are mapped locally there so this
 *     file stays icon-free and importable from node test env
 *   - the Requests action catalog (lib/requests/catalog.ts) — grouping +
 *     search keywords + gradient tints
 */

export interface ModuleDef {
  /** Stable key, used to join agents → modules. */
  key: string;
  label: string;
  href: string;
  /** Tailwind gradient classes — must match the home grid tile exactly. */
  gradient: string;
  /**
   * Lowercase keywords for (a) inferring a module for agents missing from
   * the static agent→module map and (b) catalog search.
   */
  keywords: string[];
}

export const MODULE_ROSTER: ModuleDef[] = [
  {
    key: "requests",
    label: "Requests",
    href: "/requests",
    gradient: "from-indigo-400 to-indigo-600",
    keywords: ["request", "route", "routing", "coordinator", "orchestrat", "classify"],
  },
  {
    key: "approvals",
    label: "Approvals",
    href: "/queue",
    gradient: "from-red-400 to-rose-600",
    keywords: ["approval", "approve", "queue", "sign-off", "ccb", "change control board"],
  },
  {
    key: "projects",
    label: "Projects",
    href: "/projects",
    gradient: "from-sky-400 to-blue-600",
    keywords: ["project", "schedule", "rfi", "milestone", "critical path", "gantt", "owner report", "float"],
  },
  {
    key: "sites",
    label: "Sites",
    href: "/sites",
    gradient: "from-emerald-400 to-green-600",
    keywords: ["site", "parcel", "land", "go/no-go", "datasite", "evaluation", "zoning", "fiber"],
  },
  {
    key: "contracts",
    label: "Contracts",
    href: "/contracts",
    gradient: "from-amber-400 to-orange-600",
    keywords: ["contract", "change order", "clause", "agreement", "subcontract", "terms"],
  },
  {
    key: "estimates",
    label: "Estimates",
    href: "/estimates",
    gradient: "from-teal-400 to-cyan-600",
    keywords: ["estimate", "estimator", "pricing", "cost breakdown", "takeoff", "unit rate", "bid"],
  },
  {
    key: "documents",
    label: "Documents",
    href: "/documents",
    gradient: "from-slate-400 to-slate-600",
    keywords: ["document", "submittal", "spec", "drawing", "file", "upload"],
  },
  {
    key: "operations",
    label: "Operations",
    href: "/operations",
    gradient: "from-orange-400 to-red-500",
    keywords: ["operations", "facility", "campus", "incident", "uptime", "pue", "field report", "safety", "outage", "power"],
  },
  {
    key: "sales",
    label: "Sales",
    href: "/pipeline",
    gradient: "from-fuchsia-400 to-purple-600",
    keywords: ["sales", "deal", "pipeline", "prospect", "crm", "win rate", "account"],
  },
  {
    key: "customers",
    label: "Customers",
    href: "/customers",
    gradient: "from-pink-400 to-rose-500",
    keywords: ["customer", "ticket", "support", "churn", "health score", "nps", "at-risk"],
  },
  {
    key: "supply-chain",
    label: "Supply Chain",
    href: "/supply-chain",
    gradient: "from-lime-500 to-emerald-600",
    keywords: ["supply", "procurement", "vendor", "equipment", "delivery", "lead time", "lead-time", "long-lead"],
  },
  {
    key: "finance",
    label: "Finance",
    href: "/finance",
    gradient: "from-green-500 to-emerald-700",
    keywords: ["finance", "invoice", "arr", "budget", "cash", "capex", "payment", "overdue"],
  },
  {
    key: "compliance",
    label: "Compliance",
    href: "/compliance",
    gradient: "from-blue-500 to-indigo-700",
    keywords: ["compliance", "regulatory", "permit", "obligation", "audit", "filing", "insurance", "deadline"],
  },
  {
    key: "intelligence",
    label: "Intelligence",
    href: "/intelligence",
    gradient: "from-violet-400 to-purple-700",
    keywords: ["intelligence", "executive", "kpi", "brief", "summary", "dashboard", "overview", "rollup"],
  },
  {
    key: "agents",
    label: "Agents",
    href: "/agents",
    gradient: "from-cyan-500 to-sky-700",
    keywords: ["agent", "fleet", "registry"],
  },
];

/** Lookup by key, e.g. moduleByKey("sales"). */
export function moduleByKey(key: string): ModuleDef | undefined {
  return MODULE_ROSTER.find((m) => m.key === key);
}
