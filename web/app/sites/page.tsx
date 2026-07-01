"use client";

/**
 * /sites — DataSite Intelligence pipeline board (Sprint DC.2)
 *
 * Kanban-style board showing all site evaluations grouped by pipeline status:
 *   intake | researching | scoring | review | decided
 *
 * Design: dark Quill theme, iOS-style cards, accent blue #0A84FF.
 * Matches patterns from /contracts and /estimates pages.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { Building2, Plus, MapPin, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { useSites } from "@/lib/api";
import type { Site } from "@/lib/schemas";

// ── Constants ────────────────────────────────────────────────────────────────

const PIPELINE_COLUMNS = [
  { key: "intake", label: "Intake" },
  { key: "researching", label: "Researching" },
  { key: "scoring", label: "Scoring" },
  { key: "review", label: "Review" },
  { key: "decided", label: "Decided" },
] as const;

type PipelineStatus = (typeof PIPELINE_COLUMNS)[number]["key"];

// ── Helpers ───────────────────────────────────────────────────────────────────

function verdictColor(verdict: string | null | undefined): string {
  switch (verdict) {
    case "strong_recommend": return "text-green-400 bg-green-400/10";
    case "conditional": return "text-blue-400 bg-blue-400/10";
    case "weak": return "text-yellow-400 bg-yellow-400/10";
    case "no_go": return "text-red-400 bg-red-400/10";
    default: return "text-label-tertiary bg-bg-elevated";
  }
}

function verdictLabel(verdict: string | null | undefined): string {
  switch (verdict) {
    case "strong_recommend": return "Strong Recommend";
    case "conditional": return "Conditional";
    case "weak": return "Weak";
    case "no_go": return "No-Go";
    default: return verdict ?? "";
  }
}

function workloadLabel(wt: string | null | undefined): string {
  switch (wt) {
    case "hyperscale_compute":
    case "hyperscale": return "Hyperscale";
    case "ai_hpc": return "AI/HPC";
    case "edge_latency":
    case "edge": return "Edge";
    case "colocation":
    case "enterprise_colo": return "Colo";
    case "mixed": return "Mixed";
    default: return wt ?? "—";
  }
}

function siteAddress(site: Site): string {
  const p = site.property ?? {};
  const parts = [p.address, p.city, p.state].filter(Boolean);
  return parts.join(", ") || site.site_id.slice(0, 8);
}

function scoreColor(score: number | null | undefined): string {
  if (score == null) return "text-label-tertiary";
  if (score >= 70) return "text-green-400";
  if (score >= 50) return "text-yellow-400";
  return "text-red-400";
}

// ── Site Card ─────────────────────────────────────────────────────────────────

function SiteCard({ site, onClick }: { site: Site; onClick: () => void }) {
  const score = site.scores?.total_weighted;
  const verdict = site.recommendation?.verdict;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full text-left rounded-2xl p-4 mb-3",
        "bg-chrome/80 border border-separator/40",
        "backdrop-blur-sm",
        "transition-all active:scale-[0.98] hover:border-separator/80",
        "shadow-sm shadow-black/10",
      )}
    >
      {/* Address */}
      <div className="flex items-start gap-2 mb-2">
        <MapPin className="h-3.5 w-3.5 text-accent mt-0.5 shrink-0" />
        <p className="text-callout font-medium text-label-primary leading-snug line-clamp-2">
          {siteAddress(site)}
        </p>
      </div>

      {/* Meta row */}
      <div className="flex items-center gap-2 flex-wrap">
        {site.target_workload && (
          <span className="text-caption-1 font-medium text-label-secondary bg-bg-elevated rounded-full px-2 py-0.5">
            {workloadLabel(site.target_workload)}
          </span>
        )}
        {site.target_mw != null && (
          <span className="flex items-center gap-0.5 text-caption-1 text-label-secondary">
            <Zap className="h-3 w-3 text-yellow-400" />
            {site.target_mw} MW
          </span>
        )}
      </div>

      {/* Score + verdict */}
      {(score != null || verdict) && (
        <div className="flex items-center justify-between mt-3 pt-3 border-t border-separator/30">
          {score != null && (
            <span className={cn("text-title-3 font-bold tabular-nums", scoreColor(score))}>
              {score.toFixed(0)}
              <span className="text-caption-1 font-normal text-label-tertiary">/100</span>
            </span>
          )}
          {verdict && (
            <span className={cn("text-caption-1 font-semibold rounded-full px-2 py-0.5", verdictColor(verdict))}>
              {verdictLabel(verdict)}
            </span>
          )}
        </div>
      )}
    </button>
  );
}

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
    <div className="flex-shrink-0 w-72">
      <div className="flex items-center gap-2 mb-3 px-1">
        <span className="text-footnote font-semibold text-label-secondary uppercase tracking-wide">
          {label}
        </span>
        <span className="text-caption-1 font-medium text-label-tertiary bg-bg-elevated rounded-full px-1.5 py-0.5">
          {sites.length}
        </span>
      </div>
      <div className="min-h-[120px]">
        {sites.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-separator/30 h-24 flex items-center justify-center">
            <span className="text-caption-1 text-label-quaternary">Empty</span>
          </div>
        ) : (
          sites.map((site) => (
            <SiteCard
              key={site.site_id}
              site={site}
              onClick={() => onClickSite(site.site_id)}
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
  const { data: sites = [], isLoading, error } = useSites();

  const byStatus = React.useMemo(() => {
    const map: Record<string, Site[]> = {};
    for (const col of PIPELINE_COLUMNS) map[col.key] = [];
    for (const site of sites) {
      const key = (site.status ?? "intake") as PipelineStatus;
      if (map[key]) {
        map[key].push(site);
      } else {
        map["intake"].push(site);
      }
    }
    return map;
  }, [sites]);

  const total = sites.length;

  return (
    <MobileShell>
      <TopBar
        title="Sites"
        right={
          <button
            type="button"
            onClick={() => router.push("/sites/new")}
            className="flex items-center gap-1 text-accent font-semibold text-callout"
          >
            <Plus className="h-4 w-4" />
            New
          </button>
        }
      />

      {error && (
        <div className="px-4 pt-2">
          <ErrorBanner message="Failed to load sites." />
        </div>
      )}

      {!isLoading && total === 0 && !error && (
        <div className="flex flex-col items-center justify-center px-6 pt-24 gap-4">
          <Building2 className="h-12 w-12 text-label-quaternary" />
          <div className="text-center">
            <p className="text-body font-semibold text-label-primary mb-1">
              No sites yet.
            </p>
            <p className="text-callout text-label-secondary">
              Submit your first site evaluation.
            </p>
          </div>
          <button
            type="button"
            onClick={() => router.push("/sites/new")}
            className="mt-2 flex items-center gap-2 bg-accent text-white font-semibold text-callout px-5 py-2.5 rounded-full"
          >
            <Plus className="h-4 w-4" />
            New Site
          </button>
        </div>
      )}

      {(isLoading || total > 0) && (
        <div className="overflow-x-auto pb-8 pt-3 px-4">
          <div className="flex gap-4 min-w-max">
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
          "fixed bottom-[calc(env(safe-area-inset-bottom)+72px)] right-4",
          "h-14 w-14 rounded-full bg-accent shadow-lg shadow-accent/30",
          "flex items-center justify-center",
          "transition-transform active:scale-95",
        )}
      >
        <Plus className="h-6 w-6 text-white" strokeWidth={2.5} />
      </button>
    </MobileShell>
  );
}
