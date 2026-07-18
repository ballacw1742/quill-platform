/**
 * CampusCard — Lovable redesign port.
 *
 * Visual source: quill-platform-builder/src/components/quill/operations/CampusCard.tsx
 * Data: prod Campus type from @/lib/schemas.
 * Token mapping: text-success/danger/warning (prod), shadow-card (prod),
 *   text-title-3/footnote (prod), rounded-full badges, active:scale-[0.98].
 */

import { Building2, MapPin } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Campus } from "@/lib/schemas";

// ── Exported helpers (reused in [id]/page.tsx) ──────────────────────────────

export function campusStatusBadge(status: string): { label: string; cls: string } {
  switch (status) {
    case "commissioning":
      return { label: "Commissioning", cls: "text-warning bg-warning/10" };
    case "live":
      return { label: "Live", cls: "text-success bg-success/10" };
    case "maintenance":
      return { label: "Maintenance", cls: "text-warning bg-warning/10" };
    case "decommissioned":
      return { label: "Decommissioned", cls: "text-label-tertiary bg-fill-quaternary" };
    default:
      return { label: status, cls: "text-label-secondary bg-bg-elevated" };
  }
}

export function pueColor(
  current: number | null | undefined,
  target: number | null | undefined,
): string {
  if (current == null) return "text-label-secondary";
  if (target == null) return "text-label-primary";
  return current <= target ? "text-success" : "text-danger";
}

export function uptimeColor(pct: number | null | undefined): string {
  if (pct == null) return "text-label-secondary";
  if (pct >= 99.9) return "text-success";
  if (pct >= 99.0) return "text-warning";
  return "text-danger";
}

export function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v.toFixed(3)}%`;
}

export function fmtMW(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v} MW`;
}

export function fmtPUE(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(3);
}

// ── CampusCard ───────────────────────────────────────────────────────────────

export function CampusCard({
  campus,
  onClick,
}: {
  campus: Campus;
  onClick: () => void;
}) {
  const badge = campusStatusBadge(campus.status);

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full min-h-16 mb-2.5 text-left rounded-2xl bg-bg-elevated shadow-card",
        "p-5 flex flex-col gap-4",
        "active:scale-[0.98] transition-transform no-tap-highlight",
      )}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-3 min-w-0">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-accent/10 text-accent">
            <Building2 className="h-6 w-6" />
          </span>
          <span className="text-title-3 font-semibold text-label-primary truncate">
            {campus.name}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {campus.active_p1_p2_count > 0 && (
            <span className="inline-flex items-center rounded-full bg-danger/15 px-2 py-0.5 text-footnote font-semibold text-danger">
              {campus.active_p1_p2_count} P1/P2
            </span>
          )}
          <span
            className={cn(
              "rounded-full px-2.5 py-0.5 text-footnote font-semibold",
              badge.cls,
            )}
          >
            {badge.label}
          </span>
        </div>
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-3 gap-3">
        <div className="flex flex-col gap-0.5">
          <span className="text-caption-1 font-semibold text-label-tertiary uppercase tracking-wide">
            Power
          </span>
          <span className="text-title-3 font-bold text-label-primary tabular-nums">
            {fmtMW(campus.mw_live)}
          </span>
          {campus.mw_capacity != null && (
            <span className="text-footnote text-label-secondary">
              / {fmtMW(campus.mw_capacity)}
            </span>
          )}
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-caption-1 font-semibold text-label-tertiary uppercase tracking-wide">
            PUE
          </span>
          <span
            className={cn(
              "text-title-3 font-bold tabular-nums",
              pueColor(campus.pue_current, campus.pue_target),
            )}
          >
            {fmtPUE(campus.pue_current)}
          </span>
          {campus.pue_target != null && (
            <span className="text-footnote text-label-secondary">
              target {fmtPUE(campus.pue_target)}
            </span>
          )}
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-caption-1 font-semibold text-label-tertiary uppercase tracking-wide">
            Uptime
          </span>
          <span
            className={cn(
              "text-title-3 font-bold tabular-nums",
              uptimeColor(campus.uptime_pct),
            )}
          >
            {fmtPct(campus.uptime_pct)}
          </span>
          <span className="text-footnote text-label-secondary">30-day</span>
        </div>
      </div>

      {campus.address && (
        <div className="flex items-center gap-1.5 text-subhead text-label-secondary">
          <MapPin className="h-4 w-4 shrink-0" />
          <span className="truncate">{campus.address}</span>
        </div>
      )}
    </button>
  );
}
