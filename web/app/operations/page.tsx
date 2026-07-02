"use client";

/**
 * /operations — Facility Operations module (Sprint 1A)
 *
 * Shows operating data center campuses with power, PUE, uptime, and incident feed.
 * Design: dark Quill chrome, accent blue #0A84FF, matches /projects patterns.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Building2,
  ChevronRight,
  MapPin,
  Plus,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { useCampuses, useCreateCampus } from "@/lib/api";
import type { Campus, CampusListResponse } from "@/lib/schemas";
import { CAMPUS_STATUSES } from "@/lib/schemas";

// ── Helpers ───────────────────────────────────────────────────────────────────

function campusStatusBadge(status: string): { label: string; cls: string } {
  switch (status) {
    case "commissioning": return { label: "Commissioning", cls: "text-yellow-400 bg-yellow-400/10" };
    case "live":          return { label: "Live", cls: "text-green-400 bg-green-400/10" };
    case "maintenance":   return { label: "Maintenance", cls: "text-orange-400 bg-orange-400/10" };
    case "decommissioned": return { label: "Decommissioned", cls: "text-zinc-400 bg-zinc-400/10" };
    default: return { label: status, cls: "text-label-secondary bg-bg-elevated" };
  }
}

function pueColor(current: number | null | undefined, target: number | null | undefined): string {
  if (current == null) return "text-label-secondary";
  if (target == null) return "text-label-primary";
  return current <= target ? "text-green-400" : "text-red-400";
}

function uptimeColor(pct: number | null | undefined): string {
  if (pct == null) return "text-label-secondary";
  if (pct >= 99.9) return "text-green-400";
  if (pct >= 99.0) return "text-yellow-400";
  return "text-red-400";
}

function incidentSeverityBadge(severity: string): { cls: string } {
  switch (severity) {
    case "P1": return { cls: "bg-red-500 text-white" };
    case "P2": return { cls: "bg-orange-500 text-white" };
    case "P3": return { cls: "bg-yellow-500 text-black" };
    default:   return { cls: "bg-zinc-500 text-white" };
  }
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v.toFixed(3)}%`;
}

function fmtMW(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v} MW`;
}

function fmtPUE(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(3);
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Campus Card ───────────────────────────────────────────────────────────────

function CampusCard({ campus, onClick }: { campus: Campus; onClick: () => void }) {
  const badge = campusStatusBadge(campus.status);

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full text-left rounded-2xl bg-bg-elevated border border-separator/40",
        "px-4 py-4 flex flex-col gap-3",
        "active:opacity-80 transition-opacity no-tap-highlight",
        "hover:border-accent/30",
      )}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent">
            <Building2 className="h-4 w-4" />
          </span>
          <span className="text-headline font-semibold text-label-primary truncate">
            {campus.name}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {campus.active_p1_p2_count > 0 && (
            <span className="inline-flex items-center rounded-full bg-red-500/20 px-1.5 py-0.5 text-caption-2 font-semibold text-red-400">
              {campus.active_p1_p2_count} P1/P2
            </span>
          )}
          <span className={cn("rounded-full px-2 py-0.5 text-caption-2 font-semibold", badge.cls)}>
            {badge.label}
          </span>
        </div>
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-3 gap-3">
        {/* Power */}
        <div className="flex flex-col gap-0.5">
          <span className="text-caption-2 text-label-tertiary uppercase tracking-wide">Power</span>
          <span className="text-subheadline font-semibold text-label-primary">
            {fmtMW(campus.mw_live)}
          </span>
          {campus.mw_capacity != null && (
            <span className="text-caption-2 text-label-secondary">/ {fmtMW(campus.mw_capacity)}</span>
          )}
        </div>

        {/* PUE */}
        <div className="flex flex-col gap-0.5">
          <span className="text-caption-2 text-label-tertiary uppercase tracking-wide">PUE</span>
          <span className={cn("text-subheadline font-semibold", pueColor(campus.pue_current, campus.pue_target))}>
            {fmtPUE(campus.pue_current)}
          </span>
          {campus.pue_target != null && (
            <span className="text-caption-2 text-label-secondary">target {fmtPUE(campus.pue_target)}</span>
          )}
        </div>

        {/* Uptime */}
        <div className="flex flex-col gap-0.5">
          <span className="text-caption-2 text-label-tertiary uppercase tracking-wide">Uptime</span>
          <span className={cn("text-subheadline font-semibold", uptimeColor(campus.uptime_pct))}>
            {fmtPct(campus.uptime_pct)}
          </span>
          <span className="text-caption-2 text-label-secondary">30-day</span>
        </div>
      </div>

      {campus.address && (
        <div className="flex items-center gap-1.5 text-caption-1 text-label-secondary">
          <MapPin className="h-3 w-3 shrink-0" />
          <span className="truncate">{campus.address}</span>
        </div>
      )}
    </button>
  );
}

// ── New Campus Modal ──────────────────────────────────────────────────────────

function NewCampusModal({ onClose }: { onClose: () => void }) {
  const createCampus = useCreateCampus();

  const [name, setName] = React.useState("");
  const [address, setAddress] = React.useState("");
  const [mwCapacity, setMwCapacity] = React.useState("");
  const [pueTarget, setPueTarget] = React.useState("");
  const [campusStatus, setCampusStatus] = React.useState("commissioning");
  const [projectId, setProjectId] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await createCampus.mutateAsync({
        name: name.trim(),
        address: address.trim() || null,
        mw_capacity: mwCapacity ? parseFloat(mwCapacity) : null,
        pue_target: pueTarget ? parseFloat(pueTarget) : null,
        status: campusStatus,
        project_id: projectId.trim() || null,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create campus");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 backdrop-blur-sm sm:items-center">
      <div className="w-full max-w-lg rounded-t-2xl rounded-b-none sm:rounded-2xl bg-chrome border border-separator/40 shadow-2xl pb-safe">
        <div className="flex items-center justify-between px-4 pt-4 pb-2 border-b border-separator/30">
          <h2 className="text-headline font-semibold text-label-primary">New Campus</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-label-secondary active:text-label-primary text-body"
          >
            Cancel
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3 px-4 py-4">
          {error && (
            <p className="text-caption-1 text-red-400 bg-red-400/10 rounded-xl px-3 py-2">{error}</p>
          )}

          <label className="flex flex-col gap-1">
            <span className="text-caption-1 text-label-secondary">Name *</span>
            <input
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2.5 text-body text-label-primary placeholder:text-label-tertiary focus:outline-none focus:border-accent"
              placeholder="e.g. Columbus Campus 1"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-caption-1 text-label-secondary">Address</span>
            <input
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2.5 text-body text-label-primary placeholder:text-label-tertiary focus:outline-none focus:border-accent"
              placeholder="123 Main St, Columbus, OH"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
            />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-caption-1 text-label-secondary">MW Capacity</span>
              <input
                type="number"
                step="0.1"
                min="0"
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2.5 text-body text-label-primary placeholder:text-label-tertiary focus:outline-none focus:border-accent"
                placeholder="500"
                value={mwCapacity}
                onChange={(e) => setMwCapacity(e.target.value)}
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-caption-1 text-label-secondary">PUE Target</span>
              <input
                type="number"
                step="0.01"
                min="1"
                max="3"
                className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2.5 text-body text-label-primary placeholder:text-label-tertiary focus:outline-none focus:border-accent"
                placeholder="1.20"
                value={pueTarget}
                onChange={(e) => setPueTarget(e.target.value)}
              />
            </label>
          </div>

          <label className="flex flex-col gap-1">
            <span className="text-caption-1 text-label-secondary">Status</span>
            <select
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2.5 text-body text-label-primary focus:outline-none focus:border-accent"
              value={campusStatus}
              onChange={(e) => setCampusStatus(e.target.value)}
            >
              {CAMPUS_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-caption-1 text-label-secondary">Linked Project ID (optional)</span>
            <input
              className="w-full rounded-xl bg-bg-elevated border border-separator/40 px-3 py-2.5 text-body text-label-primary placeholder:text-label-tertiary focus:outline-none focus:border-accent font-mono text-caption-1"
              placeholder="UUID of the originating project"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
            />
          </label>

          <button
            type="submit"
            disabled={!name.trim() || createCampus.isPending}
            className={cn(
              "mt-2 w-full rounded-xl py-3 text-body font-semibold transition-opacity",
              "bg-accent text-white",
              (!name.trim() || createCampus.isPending) && "opacity-40 cursor-not-allowed",
            )}
          >
            {createCampus.isPending ? "Creating…" : "Create Campus"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function OperationsPage() {
  const router = useRouter();
  const { data, isLoading, error } = useCampuses();
  const [showNewModal, setShowNewModal] = React.useState(false);

  const campuses: Campus[] = (data as CampusListResponse | undefined)?.items ?? [];

  // Collect active P1/P2 incidents across all campuses from the campus data
  // (active_p1_p2_count is computed on campus objects; for the incident feed
  // we show all campuses with active incidents and link to detail)
  const campusesWithActiveIncidents: Campus[] = campuses.filter((c) => c.active_p1_p2_count > 0);

  return (
    <MobileShell>
      <TopBar
        title={
          <span className="flex items-center gap-2">
            <Building2 className="h-4 w-4 text-accent" />
            Operations
          </span>
        }
        right={
          <button
            type="button"
            onClick={() => setShowNewModal(true)}
            aria-label="New Campus"
            className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent text-white active:opacity-70 no-tap-highlight"
          >
            <Plus className="h-5 w-5" />
          </button>
        }
      />

      <div className="px-4 py-4 flex flex-col gap-6 pb-8">

        {/* ── Campus Pipeline Board ─────────────────────────────────────── */}
        <section>
          <h2 className="text-subheadline font-semibold text-label-secondary uppercase tracking-wide mb-3">
            Campus Board
          </h2>

          {isLoading && (
            <div className="flex items-center justify-center py-12 text-label-tertiary text-body">
              Loading campuses…
            </div>
          )}

          {!isLoading && error && (
            <div className="rounded-2xl bg-red-500/10 border border-red-500/20 px-4 py-3 text-caption-1 text-red-400">
              Failed to load campuses: {error instanceof Error ? error.message : "Unknown error"}
            </div>
          )}

          {!isLoading && !error && campuses.length === 0 && (
            <div className="rounded-2xl bg-bg-elevated border border-separator/40 px-6 py-10 flex flex-col items-center gap-4 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/10 text-accent">
                <Building2 className="h-7 w-7" />
              </span>
              <div>
                <p className="text-headline font-semibold text-label-primary mb-1">No campuses yet</p>
                <p className="text-body text-label-secondary max-w-xs">
                  When a project reaches Commissioning phase, promote it here.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowNewModal(true)}
                className="mt-1 rounded-xl bg-accent px-5 py-2.5 text-body font-semibold text-white active:opacity-70"
              >
                Create Campus
              </button>
            </div>
          )}

          {!isLoading && campuses.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {campuses.map((campus) => (
                <CampusCard
                  key={campus.id}
                  campus={campus}
                  onClick={() => router.push(`/operations/${campus.id}`)}
                />
              ))}
            </div>
          )}
        </section>

        {/* ── Active Incidents Feed ────────────────────────────────────── */}
        {campusesWithActiveIncidents.length > 0 && (
          <section>
            <h2 className="text-subheadline font-semibold text-label-secondary uppercase tracking-wide mb-3">
              Active P1 / P2 Incidents
            </h2>

            <div className="rounded-2xl bg-bg-elevated border border-separator/40 overflow-hidden divide-y divide-separator/20">
              {campusesWithActiveIncidents.map((campus) => (
                <button
                  key={campus.id}
                  type="button"
                  onClick={() => router.push(`/operations/${campus.id}`)}
                  className="w-full flex items-center gap-3 px-4 py-3 text-left active:bg-bg-elevated/80 no-tap-highlight"
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-red-500/20">
                    <AlertTriangle className="h-4 w-4 text-red-400" />
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-body font-medium text-label-primary truncate">{campus.name}</p>
                    <p className="text-caption-1 text-red-400">
                      {campus.active_p1_p2_count} active P1/P2{campus.active_p1_p2_count > 1 ? " incidents" : " incident"}
                    </p>
                  </div>
                  <ChevronRight className="h-4 w-4 text-label-tertiary shrink-0" />
                </button>
              ))}
            </div>
          </section>
        )}
      </div>

      {showNewModal && <NewCampusModal onClose={() => setShowNewModal(false)} />}
    </MobileShell>
  );
}
