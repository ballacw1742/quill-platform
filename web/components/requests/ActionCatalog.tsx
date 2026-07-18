"use client";

/**
 * ActionCatalog — the Requests hub action catalog (UI_REDESIGN_BRIEF §5).
 *
 * Renders below the composer affordances on /requests: one section per
 * home-screen module (all 15, same names/order/gradient tints as the home
 * grid), each with tappable Liquid Glass action chips sourced from the live
 * agent registry (GET /v1/agents via useAgents).
 *
 * - Tapping a chip calls onChipTap → the page pre-fills + focuses the
 *   composer with the chip's prompt template.
 * - Search field filters sections/agents/chips by keyword.
 * - Loading → skeleton rows; registry unreachable → graceful fallback
 *   message (composer keeps working); no agents → empty state.
 */

import * as React from "react";
import type { LucideIcon } from "lucide-react";
import {
  Bot,
  Brain,
  Calculator,
  ClipboardList,
  DollarSign,
  Factory,
  FileText,
  FolderKanban,
  Inbox,
  MapPin,
  MessageSquare,
  Package,
  Search,
  Shield,
  TrendingUp,
  Users,
  X,
} from "lucide-react";

import { useAgents } from "@/lib/api";
import {
  buildCatalog,
  filterCatalog,
  type CatalogChip,
  type CatalogSection,
} from "@/lib/requests/catalog";
import { cn } from "@/lib/utils";

/* Same icon-per-module mapping as the home grid (app/page.tsx). */
const MODULE_ICONS: Record<string, LucideIcon> = {
  requests: MessageSquare,
  approvals: Inbox,
  projects: FolderKanban,
  sites: MapPin,
  contracts: ClipboardList,
  estimates: Calculator,
  documents: FileText,
  operations: Factory,
  sales: TrendingUp,
  customers: Users,
  "supply-chain": Package,
  finance: DollarSign,
  compliance: Shield,
  intelligence: Brain,
  agents: Bot,
};

export function ActionCatalog({
  onChipTap,
}: {
  onChipTap: (chip: CatalogChip) => void;
}) {
  const { data: agentsRaw, isLoading, error, refetch } = useAgents();
  const [query, setQuery] = React.useState("");

  // Defensive: hook returns Agent[], but tolerate {items} envelopes like
  // the Agents page does.
  const agents = React.useMemo(() => {
    if (!agentsRaw) return [];
    if (Array.isArray(agentsRaw)) return agentsRaw;
    return (agentsRaw as { items?: typeof agentsRaw }).items ?? [];
  }, [agentsRaw]);

  const catalog = React.useMemo(() => buildCatalog(agents), [agents]);
  const filtered = React.useMemo(() => filterCatalog(catalog, query), [catalog, query]);

  const hasAgents = agents.length > 0;
  const searching = query.trim().length > 0;

  return (
    <section aria-label="Action catalog" className="px-4 pb-2">
      <h2 className="pt-1 pb-2 text-title-3 font-semibold text-label-primary">
        What can I do here?
      </h2>

      {/* Search */}
      <div className="relative mb-3">
        <Search
          className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-label-tertiary"
          aria-hidden
        />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search actions, agents, modules…"
          aria-label="Search the action catalog"
          className={cn(
            "glass w-full rounded-2xl py-2.5 pl-10 pr-10 min-h-[44px]",
            "text-body text-label-primary placeholder:text-label-tertiary",
            "focus:outline-none focus:ring-2 focus:ring-accent/50",
            "[&::-webkit-search-cancel-button]:hidden",
          )}
        />
        {searching && (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label="Clear search"
            className="absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full text-label-secondary active:opacity-60 no-tap-highlight"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        )}
      </div>

      {/* States */}
      {isLoading ? (
        <CatalogSkeleton />
      ) : error ? (
        <div
          role="alert"
          className="glass flex flex-col items-start gap-2 rounded-2xl p-4"
        >
          <p className="text-body text-label-primary">
            Couldn&apos;t load the action catalog.
          </p>
          <p className="text-footnote text-label-secondary">
            You can still type any request below — the coordinator will route it.
          </p>
          <button
            type="button"
            onClick={() => refetch()}
            className="mt-1 min-h-[44px] rounded-full bg-accent/10 px-4 text-callout font-medium text-accent active:opacity-70 no-tap-highlight"
          >
            Try again
          </button>
        </div>
      ) : !hasAgents ? (
        <div className="glass rounded-2xl p-4">
          <p className="text-body text-label-primary">No agents registered yet.</p>
          <p className="mt-1 text-footnote text-label-secondary">
            Actions appear here as agents are registered. You can still type any
            request below.
          </p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="glass rounded-2xl p-4">
          <p className="text-body text-label-primary">
            No actions match &ldquo;{query.trim()}&rdquo;.
          </p>
          <p className="mt-1 text-footnote text-label-secondary">
            Try a different keyword, or just type your request below.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          {filtered.map((section) => (
            <ModuleSection key={section.module.key} section={section} onChipTap={onChipTap} />
          ))}
        </div>
      )}
    </section>
  );
}

/* ── One module section ────────────────────────────────────────────────── */

function ModuleSection({
  section,
  onChipTap,
}: {
  section: CatalogSection;
  onChipTap: (chip: CatalogChip) => void;
}) {
  const Icon = MODULE_ICONS[section.module.key] ?? Bot;
  return (
    <div>
      <div className="mb-2 flex items-center gap-2.5">
        <span
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-[28%] bg-gradient-to-br text-white",
            "shadow-[0_1px_4px_rgba(0,0,0,0.14),inset_0_1px_0_rgba(255,255,255,0.25)]",
            section.module.gradient,
          )}
          aria-hidden="true"
        >
          <Icon className="h-4 w-4" strokeWidth={1.9} />
        </span>
        <h3 className="text-headline text-label-primary">{section.module.label}</h3>
      </div>

      {section.chips.length === 0 ? (
        <p className="pl-[38px] text-footnote text-label-tertiary">
          No agent actions here yet.
        </p>
      ) : (
        <div className="flex flex-wrap gap-2" role="list" aria-label={`${section.module.label} actions`}>
          {section.chips.map((c) => (
            <ActionChip key={c.id} chip={c} onTap={onChipTap} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── One chip ──────────────────────────────────────────────────────────── */

function ActionChip({
  chip,
  onTap,
}: {
  chip: CatalogChip;
  onTap: (chip: CatalogChip) => void;
}) {
  const [pressed, setPressed] = React.useState(false);
  // Sprint 5.5 (G8) — honesty badge: workflow-fleet agents aren't invocable
  // via POST /v1/requests; their chips reroute to the intent's ADK executor.
  // Badge the reroute so the demo never claims an agent ran when it didn't.
  const rerouted = !chip.direct;
  const hoverText = rerouted
    ? `Runs via ${chip.executorAgentName}${chip.template ? ` — ${chip.template.trim()}` : ""}`
    : `${chip.agentName}${chip.template ? ` — ${chip.template.trim()}` : ""}`;
  return (
    <button
      type="button"
      role="listitem"
      onClick={() => onTap(chip)}
      onPointerDown={() => setPressed(true)}
      onPointerUp={() => setPressed(false)}
      onPointerLeave={() => setPressed(false)}
      onPointerCancel={() => setPressed(false)}
      title={hoverText}
      aria-label={
        rerouted
          ? `${chip.label} (runs via ${chip.executorAgentName})`
          : `${chip.label} (${chip.agentName})`
      }
      className={cn(
        "glass min-h-[44px] rounded-full px-4 py-2 text-left",
        "text-callout font-medium text-label-primary",
        "no-tap-highlight transition-transform duration-tap ease-ios",
        pressed ? "scale-[0.96]" : "scale-100",
      )}
    >
      {chip.label}
      {rerouted && (
        <span className="ml-1.5 align-middle text-[11px] font-normal text-label-tertiary">
          via {chip.executorAgentName}
        </span>
      )}
    </button>
  );
}

/* ── Loading skeleton ──────────────────────────────────────────────────── */

function CatalogSkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-label="Loading actions" role="status">
      {[0, 1, 2].map((row) => (
        <div key={row}>
          <div className="mb-2 flex items-center gap-2.5">
            <span className="h-7 w-7 animate-pulse rounded-[28%] bg-bg-elevated" />
            <span className="h-4 w-28 animate-pulse rounded bg-bg-elevated" />
          </div>
          <div className="flex flex-wrap gap-2">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="h-[44px] animate-pulse rounded-full bg-bg-elevated"
                style={{ width: `${110 + ((row + i) % 3) * 30}px` }}
              />
            ))}
          </div>
        </div>
      ))}
      <span className="sr-only">Loading action catalog…</span>
    </div>
  );
}
