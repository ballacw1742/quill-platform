"use client";

/**
 * /operations — Facility Operations module (Lovable redesign port).
 *
 * Visual source: quill-platform-builder/src/routes/operations.tsx
 * Data: prod useCampuses / useCreateCampus from @/lib/api.
 * Envelope: useCampuses() → CampusListResponse → data?.items ?? [].
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Building2, ChevronRight, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { CampusCard } from "@/components/operations/CampusCard";
import { useCampuses, useCreateCampus } from "@/lib/api";
import type { Campus, CampusListResponse } from "@/lib/schemas";
import { CAMPUS_STATUSES } from "@/lib/schemas";

// ── Shared form primitives ────────────────────────────────────────────────────

const inputCls =
  "w-full rounded-xl bg-bg-elevated shadow-card px-3 py-2.5 text-body text-label-primary placeholder:text-label-tertiary focus:outline-none focus:border-accent";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-caption-1 text-label-secondary">{label}</span>
      {children}
    </label>
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
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 backdrop-blur-sm sm:items-center">
      <div className="w-full max-w-lg rounded-t-2xl sm:rounded-2xl bg-chrome border border-hairline shadow-2xl pb-safe">
        <div className="flex items-center justify-between px-4 pt-4 pb-2 border-b border-hairline">
          <h2 className="text-headline font-semibold text-label-primary">
            New Campus
          </h2>
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
            <p className="text-caption-1 text-danger bg-danger/10 rounded-xl px-3 py-2">
              {error}
            </p>
          )}

          <Field label="Name *">
            <input
              className={inputCls}
              placeholder="e.g. Columbus Campus 1"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </Field>

          <Field label="Address">
            <input
              className={inputCls}
              placeholder="123 Main St, Columbus, OH"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="MW Capacity">
              <input
                type="number"
                step="0.1"
                min="0"
                className={inputCls}
                placeholder="500"
                value={mwCapacity}
                onChange={(e) => setMwCapacity(e.target.value)}
              />
            </Field>
            <Field label="PUE Target">
              <input
                type="number"
                step="0.01"
                min="1"
                max="3"
                className={inputCls}
                placeholder="1.20"
                value={pueTarget}
                onChange={(e) => setPueTarget(e.target.value)}
              />
            </Field>
          </div>

          <Field label="Status">
            <select
              className={inputCls}
              value={campusStatus}
              onChange={(e) => setCampusStatus(e.target.value)}
            >
              {CAMPUS_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Linked Project ID (optional)">
            <input
              className={cn(inputCls, "font-mono text-caption-1")}
              placeholder="UUID of the originating project"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
            />
          </Field>

          <button
            type="submit"
            disabled={!name.trim() || createCampus.isPending}
            className={cn(
              "mt-2 w-full rounded-full py-3 text-body font-semibold transition-all",
              "bg-accent text-primary-foreground shadow-card hover:bg-accent-pressed hover:shadow-elevated active:scale-[0.98]",
              (!name.trim() || createCampus.isPending) &&
                "opacity-40 cursor-not-allowed",
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

  // Prod hook returns CampusListResponse { items, total, limit, offset }
  const campuses: Campus[] = (data as CampusListResponse | undefined)?.items ?? [];
  const withActive = campuses.filter((c) => c.active_p1_p2_count > 0);

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
            className="flex h-9 w-9 items-center justify-center rounded-full bg-accent text-primary-foreground shadow-card hover:bg-accent-pressed hover:shadow-elevated active:scale-[0.98] transition-all no-tap-highlight"
          >
            <Plus className="h-5 w-5" />
          </button>
        }
      />

      <div className="px-4 py-4 flex flex-col gap-6 pb-8">
        {/* ── Campus Board ─────────────────────────────────────────────── */}
        <section>
          <h2 className="text-subhead font-semibold text-label-secondary uppercase tracking-wide mb-3">
            Campus Board
          </h2>

          {isLoading && (
            <div className="flex items-center justify-center py-12 text-label-tertiary text-body">
              Loading campuses…
            </div>
          )}

          {!isLoading && error && (
            <div className="rounded-2xl bg-danger/10 border border-danger/20 px-4 py-3 text-caption-1 text-danger">
              Failed to load campuses:{" "}
              {error instanceof Error ? error.message : "Unknown error"}
            </div>
          )}

          {!isLoading && !error && campuses.length === 0 && (
            <div className="rounded-2xl bg-bg-elevated border border-separator/40 px-6 py-10 flex flex-col items-center gap-4 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/10 text-accent">
                <Building2 className="h-7 w-7" />
              </span>
              <div>
                <p className="text-headline font-semibold text-label-primary mb-1">
                  No campuses yet
                </p>
                <p className="text-body text-label-secondary max-w-xs">
                  When a project reaches commissioning phase, promote it here.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowNewModal(true)}
                className="rounded-full bg-accent px-5 py-2.5 text-body font-semibold text-primary-foreground shadow-card hover:bg-accent-pressed hover:shadow-elevated active:scale-[0.98] transition-all active:opacity-70"
              >
                Create Campus
              </button>
            </div>
          )}

          {!isLoading && campuses.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {campuses.map((c) => (
                <CampusCard
                  key={c.id}
                  campus={c}
                  onClick={() => router.push(`/operations/${c.id}`)}
                />
              ))}
            </div>
          )}
        </section>

        {/* ── Active P1 / P2 Incidents Feed ────────────────────────────── */}
        {withActive.length > 0 && (
          <section>
            <h2 className="text-subhead font-semibold text-label-secondary uppercase tracking-wide mb-3">
              Active P1 / P2 Incidents
            </h2>
            <div className="rounded-2xl bg-bg-elevated border border-separator/40 overflow-hidden divide-y divide-separator/20">
              {withActive.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => router.push(`/operations/${c.id}`)}
                  className="w-full flex items-center gap-3 px-4 py-3 text-left active:opacity-80 no-tap-highlight"
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-danger/20">
                    <AlertTriangle className="h-4 w-4 text-danger" />
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-body font-medium text-label-primary truncate">
                      {c.name}
                    </p>
                    <p className="text-caption-1 text-danger">
                      {c.active_p1_p2_count} active P1/P2
                      {c.active_p1_p2_count > 1 ? " incidents" : " incident"}
                    </p>
                  </div>
                  <ChevronRight className="h-4 w-4 text-label-tertiary shrink-0" />
                </button>
              ))}
            </div>
          </section>
        )}
      </div>

      {showNewModal && (
        <NewCampusModal onClose={() => setShowNewModal(false)} />
      )}
    </MobileShell>
  );
}
