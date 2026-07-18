"use client";

/**
 * /sites — DataSite Intelligence pipeline board
 *
 * Kanban-style board showing all site evaluations grouped by pipeline status:
 *   intake | researching | scoring | review | decided
 *
 * Visual layer ported from quill-platform-builder/src/routes/sites.tsx.
 * Data wired to prod useSites() from @/lib/api (returns Site[] bare array).
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { Building2, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { SiteCard } from "@/components/sites/SiteCard";
import { useSites } from "@/lib/api";
import type { Site } from "@/lib/schemas";

// ── Constants ────────────────────────────────────────────────────────────────

type PipelineStatus = "intake" | "researching" | "scoring" | "review" | "decided";

const PIPELINE_COLUMNS: { key: PipelineStatus; label: string }[] = [
  { key: "intake",      label: "Intake" },
  { key: "researching", label: "Researching" },
  { key: "scoring",     label: "Scoring" },
  { key: "review",      label: "Review" },
  { key: "decided",     label: "Decided" },
];

// ── Column ────────────────────────────────────────────────────────────────────

function Column({
  label,
  sites,
  onClickSite,
}: {
  label: string;
  sites: Site[];
  onClickSite: (id: string) => void;
}) {
  return (
    <div className="w-full md:w-72 md:shrink-0">
      <div className="mb-3 flex items-center gap-2 px-1">
        <span className="text-footnote font-semibold uppercase tracking-wide text-label-secondary">
          {label}
        </span>
        <span className="text-caption-1 rounded-full bg-bg-elevated px-1.5 py-0.5 font-medium text-label-tertiary border border-hairline">
          {sites.length}
        </span>
      </div>
      <div className="min-h-[64px]">
        {sites.length === 0 ? (
          <div className="flex h-16 items-center justify-center rounded-2xl bg-bg-elevated shadow-card">
            <span className="text-footnote text-label-tertiary">Empty</span>
          </div>
        ) : (
          sites.map((s) => (
            <SiteCard
              key={s.site_id}
              site={s}
              onClick={() => onClickSite(s.site_id)}
            />
          ))
        )}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SitesPage() {
  const router = useRouter();
  // useSites() returns Site[] directly (normalized by prod hook)
  const { data: sites = [], isLoading, error } = useSites();

  const byStatus = React.useMemo(() => {
    const map: Record<PipelineStatus, Site[]> = {
      intake: [], researching: [], scoring: [], review: [], decided: [],
    };
    for (const s of sites) {
      const key = (s.status ?? "intake") as PipelineStatus;
      if (map[key]) {
        map[key].push(s);
      } else {
        map["intake"].push(s);
      }
    }
    return map;
  }, [sites]);

  return (
    <MobileShell>
      <TopBar
        title="Sites"
        right={
          <button
            type="button"
            onClick={() => router.push("/sites/new")}
            className="text-callout flex items-center gap-1 font-semibold text-accent"
          >
            <Plus className="h-4 w-4" />
            New
          </button>
        }
      />

      {error && (
        <div className="mx-auto w-full max-w-[708px] px-4 pt-3 md:max-w-4xl md:px-8">
          <div className="rounded-xl border border-danger/30 bg-danger/10 p-3 text-callout text-danger">
            Failed to load sites.
          </div>
        </div>
      )}

      {!isLoading && sites.length === 0 && !error && (
        <div className="flex flex-col items-center justify-center gap-4 px-6 pt-24">
          <Building2 className="h-12 w-12 text-label-quaternary" />
          <div className="text-center">
            <p className="mb-1 text-body font-semibold text-label-primary">No sites yet.</p>
            <p className="text-callout text-label-secondary">Submit your first site evaluation.</p>
          </div>
          <button
            type="button"
            onClick={() => router.push("/sites/new")}
            className="mt-2 flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-callout font-semibold text-white"
          >
            <Plus className="h-4 w-4" />
            New Site
          </button>
        </div>
      )}

      {(isLoading || sites.length > 0) && (
        <div className="px-4 pt-3 pb-8 md:overflow-x-auto">
          <div className="flex flex-col gap-6 md:min-w-max md:flex-row md:gap-4">
            {PIPELINE_COLUMNS.map((col) => (
              <Column
                key={col.key}
                label={col.label}
                sites={byStatus[col.key] ?? []}
                onClickSite={(id) => router.push(`/sites/${id}`)}
              />
            ))}
          </div>
        </div>
      )}

      {/* FAB */}
      <button
        type="button"
        aria-label="New site"
        onClick={() => router.push("/sites/new")}
        className={cn(
          "fixed bottom-[calc(env(safe-area-inset-bottom)+96px)] right-4 z-40",
          "flex h-14 w-14 items-center justify-center rounded-full bg-accent",
          "shadow-lg shadow-accent/30",
          "transition-transform active:scale-95 no-tap-highlight",
        )}
      >
        <Plus className="h-6 w-6 text-white" strokeWidth={2.5} />
      </button>
    </MobileShell>
  );
}
