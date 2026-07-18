"use client";

/**
 * SiteCard — shared card component for the Sites module.
 * Visual layer ported from quill-platform-builder/src/components/quill/sites/SiteCard.tsx.
 * Wired to prod Site type from @/lib/schemas.
 */

import { MapPin, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Site } from "@/lib/schemas";

// ── Exported helpers (reused in detail page) ──────────────────────────────────

export function siteAddress(site: Site): string {
  const p = site.property ?? {};
  const parts = [p.address, p.city, p.state].filter(Boolean);
  return parts.join(", ") || site.site_id.slice(0, 12);
}

export function workloadLabel(wt: string | null | undefined): string {
  switch (wt) {
    case "hyperscale_compute":
    case "hyperscale":
      return "Hyperscale";
    case "ai_hpc":
      return "AI/HPC";
    case "edge_latency":
    case "edge":
      return "Edge";
    case "colocation":
    case "enterprise_colo":
      return "Colo";
    case "mixed":
      return "Mixed";
    default:
      return wt ?? "—";
  }
}

export function verdictInfo(v: string | null | undefined): { label: string; cls: string } {
  switch (v) {
    case "strong_recommend":
      return { label: "Strong Recommend", cls: "text-success bg-success/10" };
    case "conditional":
      return { label: "Conditional", cls: "text-info bg-info/10" };
    case "weak":
      return { label: "Weak", cls: "text-warning bg-warning/10" };
    case "no_go":
      return { label: "No-Go", cls: "text-danger bg-danger/10" };
    default:
      return { label: "—", cls: "text-label-tertiary bg-bg-elevated" };
  }
}

export function scoreColor(score: number | null | undefined): string {
  if (score == null) return "text-label-tertiary";
  if (score >= 70) return "text-success";
  if (score >= 50) return "text-warning";
  return "text-danger";
}

// ── Component ─────────────────────────────────────────────────────────────────

export function SiteCard({ site, onClick }: { site: Site; onClick: () => void }) {
  const score = site.scores?.total_weighted;
  const verdict = site.recommendation?.verdict;
  const v = verdictInfo(verdict);

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "mb-2.5 w-full min-h-16 rounded-2xl bg-bg-elevated p-5 text-left",
        "shadow-card",
        "transition-transform active:scale-[0.98] no-tap-highlight",
      )}
    >
      <div className="mb-2 flex items-start gap-2">
        <MapPin className="mt-1 h-4 w-4 shrink-0 text-accent" />
        <p className="text-headline line-clamp-2 font-semibold leading-snug text-label-primary">
          {siteAddress(site)}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {site.target_workload && (
          <span className="text-footnote rounded-full bg-bg-elevated px-2.5 py-0.5 font-semibold text-label-secondary border border-hairline">
            {workloadLabel(site.target_workload)}
          </span>
        )}
        {site.target_mw != null && (
          <span className="text-footnote flex items-center gap-1 font-medium text-label-secondary">
            <Zap className="h-3.5 w-3.5 text-warning" />
            {site.target_mw} MW
          </span>
        )}
      </div>

      {(score != null || verdict) && (
        <div className="mt-3 flex items-center justify-between border-t border-hairline pt-3">
          {score != null ? (
            <span className={cn("text-title-3 font-bold tabular-nums", scoreColor(score))}>
              {score.toFixed(0)}
              <span className="text-footnote font-normal text-label-tertiary">/100</span>
            </span>
          ) : (
            <span />
          )}
          {verdict && (
            <span className={cn("text-footnote rounded-full px-2.5 py-0.5 font-semibold", v.cls)}>
              {v.label}
            </span>
          )}
        </div>
      )}
    </button>
  );
}
