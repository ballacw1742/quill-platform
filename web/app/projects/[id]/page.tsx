"use client";

/**
 * /projects/[id] — Project detail (Sprint DC.2)
 *
 * Shows project name, address, 6-step phase stepper, site linkage if from site,
 * phase advance button, notes editing.
 *
 * Design: dark Quill theme, iOS-style cards.
 */

import * as React from "react";
import { useRouter, useParams } from "next/navigation";
import {
  ArrowLeft,
  ChevronRight,
  ExternalLink,
  Loader2,
  MapPin,
  Pencil,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { useProject, useUpdateProject } from "@/lib/api";
import type { QuillProject } from "@/lib/schemas";

// ── Phase config ──────────────────────────────────────────────────────────────

const PHASES = [
  { key: "site_control", label: "Site Control" },
  { key: "permitting", label: "Permitting" },
  { key: "design", label: "Design" },
  { key: "construction", label: "Construction" },
  { key: "commissioning", label: "Commissioning" },
  { key: "turnover", label: "Turnover" },
] as const;

// ── Helpers ───────────────────────────────────────────────────────────────────

function phaseIndex(phase: string): number {
  return PHASES.findIndex((p) => p.key === phase);
}

function statusBadge(status: string): { label: string; cls: string } {
  switch (status) {
    case "active": return { label: "Active", cls: "text-green-400 bg-green-400/10" };
    case "on_hold": return { label: "On Hold", cls: "text-yellow-400 bg-yellow-400/10" };
    case "complete": return { label: "Complete", cls: "text-blue-400 bg-blue-400/10" };
    case "cancelled": return { label: "Cancelled", cls: "text-red-400 bg-red-400/10" };
    default: return { label: status, cls: "text-label-secondary bg-bg-elevated" };
  }
}

function verdictLabel(verdict: string | null | undefined): { label: string; cls: string } | null {
  switch (verdict) {
    case "strong_recommend": return { label: "Strong Recommend", cls: "text-green-400 bg-green-400/10" };
    case "conditional": return { label: "Conditional", cls: "text-blue-400 bg-blue-400/10" };
    case "weak": return { label: "Weak", cls: "text-yellow-400 bg-yellow-400/10" };
    case "no_go": return { label: "No-Go", cls: "text-red-400 bg-red-400/10" };
    default: return null;
  }
}

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-2xl bg-chrome/80 border border-separator/40 p-5 mb-4", className)}>
      {children}
    </div>
  );
}

// ── Phase Stepper ─────────────────────────────────────────────────────────────

function PhaseStepper({ phase }: { phase: string }) {
  const currentIdx = phaseIndex(phase);

  return (
    <div className="space-y-1">
      {PHASES.map((p, i) => {
        const done = i < currentIdx;
        const active = i === currentIdx;
        const future = i > currentIdx;

        return (
          <div key={p.key} className="flex items-center gap-3">
            {/* Step dot */}
            <div
              className={cn(
                "w-6 h-6 rounded-full border-2 flex items-center justify-center shrink-0 text-caption-1 font-bold",
                done && "border-accent bg-accent text-white",
                active && "border-accent bg-accent/10 text-accent",
                future && "border-separator/40 bg-transparent text-label-quaternary",
              )}
            >
              {done ? "✓" : i + 1}
            </div>

            {/* Step label */}
            <span
              className={cn(
                "text-callout",
                done && "text-label-secondary",
                active && "text-label-primary font-semibold",
                future && "text-label-quaternary",
              )}
            >
              {p.label}
            </span>

            {active && (
              <span className="ml-auto text-caption-1 font-semibold text-accent">Current</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Notes Editor ──────────────────────────────────────────────────────────────

function NotesSection({ project }: { project: QuillProject }) {
  const updateProject = useUpdateProject();
  const [editing, setEditing] = React.useState(false);
  const [value, setValue] = React.useState(project.notes ?? "");

  function handleSave() {
    updateProject.mutate(
      { id: project.id, body: { notes: value } },
      {
        onSuccess: () => setEditing(false),
      },
    );
  }

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <p className="text-callout font-semibold text-label-primary">Notes</p>
        {!editing && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="text-accent text-callout flex items-center gap-1"
          >
            <Pencil className="h-3.5 w-3.5" />
            Edit
          </button>
        )}
      </div>
      {editing ? (
        <>
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={4}
            placeholder="Add notes about this project…"
            className="w-full rounded-xl px-4 py-3 text-body text-label-primary bg-bg-elevated border border-separator/60 placeholder:text-label-quaternary focus:outline-none focus:border-accent resize-none"
            autoFocus
          />
          <div className="flex gap-3 mt-3">
            <button
              type="button"
              disabled={updateProject.isPending}
              onClick={handleSave}
              className="flex-1 py-2.5 rounded-xl bg-accent text-white font-semibold text-callout disabled:opacity-60"
            >
              {updateProject.isPending ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => { setValue(project.notes ?? ""); setEditing(false); }}
              className="flex-1 py-2.5 rounded-xl border border-separator/60 text-label-primary font-semibold text-callout"
            >
              Cancel
            </button>
          </div>
        </>
      ) : (
        <p className={cn("text-callout leading-relaxed", value ? "text-label-secondary" : "text-label-quaternary")}>
          {value || "No notes yet. Tap Edit to add."}
        </p>
      )}
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ProjectDetailPage() {
  const router = useRouter();
  const params = useParams();
  const projectId = params.id as string;

  const { data: project, isLoading, error } = useProject(projectId);
  const updateProject = useUpdateProject();

  if (isLoading) {
    return (
      <MobileShell>
        <TopBar
          title="Project"
          left={
            <button type="button" onClick={() => router.back()} className="text-accent font-semibold text-callout flex items-center gap-1">
              <ArrowLeft className="h-4 w-4" /> Projects
            </button>
          }
        />
        <div className="flex items-center justify-center pt-24">
          <Loader2 className="h-8 w-8 text-label-quaternary animate-spin" />
        </div>
      </MobileShell>
    );
  }

  if (error || !project) {
    return (
      <MobileShell>
        <TopBar
          title="Project"
          left={
            <button type="button" onClick={() => router.back()} className="text-accent font-semibold text-callout flex items-center gap-1">
              <ArrowLeft className="h-4 w-4" /> Projects
            </button>
          }
        />
        <div className="px-4 pt-6 text-center text-label-secondary">
          {error ? "Failed to load project." : "Project not found."}
        </div>
      </MobileShell>
    );
  }

  const { label: statusLabel, cls: statusCls } = statusBadge(project.status);
  const vb = verdictLabel(project.site_verdict);
  const currentPhaseIdx = phaseIndex(project.phase);
  const isLastPhase = currentPhaseIdx === PHASES.length - 1;

  function handleAdvancePhase() {
    updateProject.mutate({ id: project!.id, body: { advance_phase: true } });
  }

  return (
    <MobileShell>
      <TopBar
        title={project.name}
        left={
          <button
            type="button"
            onClick={() => router.back()}
            className="text-accent font-semibold text-callout flex items-center gap-1"
          >
            <ArrowLeft className="h-4 w-4" />
            Projects
          </button>
        }
      />

      <div className="px-4 pt-3 pb-12">
        {/* Header card */}
        <Card>
          <p className="text-headline font-bold text-label-primary mb-1">{project.name}</p>
          {project.address && (
            <div className="flex items-center gap-1 mb-3">
              <MapPin className="h-3.5 w-3.5 text-label-tertiary shrink-0" />
              <p className="text-callout text-label-secondary">{project.address}</p>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <span className={cn("text-caption-1 font-semibold rounded-full px-2 py-0.5", statusCls)}>
              {statusLabel}
            </span>
            {project.workload_type && (
              <span className="text-caption-1 font-medium text-label-secondary bg-bg-elevated rounded-full px-2 py-0.5">
                {workloadLabel(project.workload_type)}
              </span>
            )}
          </div>

          {/* Site linkage */}
          {project.site_id && (
            <div className="mt-3 pt-3 border-t border-separator/30 flex items-center gap-3">
              <div className="flex-1">
                <p className="text-footnote text-label-tertiary">From Site Evaluation</p>
                <div className="flex items-center gap-2 mt-0.5">
                  {project.site_score != null && (
                    <span className={cn("text-callout font-bold tabular-nums", scoreColor(project.site_score))}>
                      {project.site_score.toFixed(0)}/100
                    </span>
                  )}
                  {vb && (
                    <span className={cn("text-caption-1 font-semibold rounded-full px-2 py-0.5", vb.cls)}>
                      {vb.label}
                    </span>
                  )}
                </div>
              </div>
              <button
                type="button"
                onClick={() => router.push(`/sites/${project.site_id}`)}
                className="flex items-center gap-1 text-accent text-caption-1 font-semibold"
              >
                View Site
                <ExternalLink className="h-3 w-3" />
              </button>
            </div>
          )}
        </Card>

        {/* Phase tracker */}
        <Card>
          <p className="text-callout font-semibold text-label-primary mb-4">Phase Tracker</p>
          <PhaseStepper phase={project.phase} />

          {/* Advance button */}
          {!isLastPhase && (
            <button
              type="button"
              disabled={updateProject.isPending}
              onClick={handleAdvancePhase}
              className={cn(
                "mt-4 w-full py-3 rounded-xl font-semibold text-callout",
                "border border-accent text-accent",
                "flex items-center justify-center gap-2",
                "transition-all active:scale-[0.98]",
                updateProject.isPending && "opacity-60 cursor-not-allowed",
              )}
            >
              {updateProject.isPending ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Advancing…</>
              ) : (
                <>
                  Advance to {PHASES[currentPhaseIdx + 1]?.label}
                  <ChevronRight className="h-4 w-4" />
                </>
              )}
            </button>
          )}

          {isLastPhase && (
            <div className="mt-4 rounded-xl bg-accent/10 border border-accent/20 px-4 py-3 text-center">
              <p className="text-callout font-semibold text-accent">🎉 Project Complete</p>
              <p className="text-caption-1 text-label-secondary mt-0.5">This project has reached Turnover.</p>
            </div>
          )}
        </Card>

        {/* Notes */}
        <NotesSection project={project} />

        {/* Timestamps */}
        <div className="px-1 text-caption-1 text-label-quaternary space-y-1">
          <p>Created {new Date(project.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</p>
          <p>Updated {new Date(project.updated_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</p>
        </div>
      </div>
    </MobileShell>
  );
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
    default: return wt ?? "";
  }
}

function scoreColor(score: number | null | undefined): string {
  if (score == null) return "text-label-tertiary";
  if (score >= 70) return "text-green-400";
  if (score >= 50) return "text-yellow-400";
  return "text-red-400";
}
