"use client";

/**
 * /projects — Project list (Sprint DC.2)
 *
 * Shows all Quill projects with phase progress indicator.
 * Projects can be created from DataSite site evaluations or standalone.
 *
 * Design: dark Quill theme, iOS-style cards, matches /contracts patterns.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { Building2, ChevronRight, FolderKanban, MapPin, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { useProjects, useCreateProject } from "@/lib/api";
import type { QuillProject } from "@/lib/schemas";

// ── Phase config ──────────────────────────────────────────────────────────────

const PHASES = [
  { key: "site_control", label: "Site Control", short: "SC" },
  { key: "permitting", label: "Permitting", short: "PM" },
  { key: "design", label: "Design", short: "DS" },
  { key: "construction", label: "Construction", short: "CN" },
  { key: "commissioning", label: "Commissioning", short: "CX" },
  { key: "turnover", label: "Turnover", short: "TO" },
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

function verdictBadge(verdict: string | null | undefined): { label: string; cls: string } | null {
  switch (verdict) {
    case "strong_recommend": return { label: "Strong Rec", cls: "text-green-400" };
    case "conditional": return { label: "Conditional", cls: "text-blue-400" };
    case "weak": return { label: "Weak", cls: "text-yellow-400" };
    case "no_go": return { label: "No-Go", cls: "text-red-400" };
    default: return null;
  }
}

// ── Phase Progress Pill ───────────────────────────────────────────────────────

function PhaseProgressPill({ phase }: { phase: string }) {
  const currentIdx = phaseIndex(phase);

  return (
    <div className="flex items-center gap-0.5 mt-3">
      {PHASES.map((p, i) => (
        <React.Fragment key={p.key}>
          <div
            className={cn(
              "flex-1 h-1.5 rounded-full transition-colors",
              i < currentIdx
                ? "bg-accent/60"
                : i === currentIdx
                  ? "bg-accent"
                  : "bg-separator/40",
            )}
          />
        </React.Fragment>
      ))}
    </div>
  );
}

// ── Project Card ──────────────────────────────────────────────────────────────

function ProjectCard({
  project,
  onClick,
}: {
  project: QuillProject;
  onClick: () => void;
}) {
  const { label: statusLabel, cls: statusCls } = statusBadge(project.status);
  const vb = verdictBadge(project.site_verdict);
  const currentPhase = PHASES.find((p) => p.key === project.phase);

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
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-callout font-semibold text-label-primary truncate">{project.name}</p>
          {project.address && (
            <div className="flex items-center gap-1 mt-0.5">
              <MapPin className="h-3 w-3 text-label-tertiary shrink-0" />
              <p className="text-caption-1 text-label-secondary truncate">{project.address}</p>
            </div>
          )}
        </div>
        <ChevronRight className="h-4 w-4 text-label-quaternary shrink-0 mt-0.5" />
      </div>

      {/* Meta */}
      <div className="flex items-center gap-2 flex-wrap mt-2">
        <span className={cn("text-caption-1 font-semibold rounded-full px-2 py-0.5", statusCls)}>
          {statusLabel}
        </span>
        {currentPhase && (
          <span className="text-caption-1 text-label-secondary">
            {currentPhase.label}
          </span>
        )}
        {project.site_score != null && (
          <span className="text-caption-1 text-label-tertiary tabular-nums">
            Score: {project.site_score.toFixed(0)}
          </span>
        )}
        {vb && (
          <span className={cn("text-caption-1 font-medium", vb.cls)}>
            {vb.label}
          </span>
        )}
      </div>

      {/* Phase bar */}
      <PhaseProgressPill phase={project.phase} />
    </button>
  );
}

// ── Create Project Sheet (simple inline form) ─────────────────────────────────

function CreateProjectModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const createProject = useCreateProject({
    onSuccess: (p: QuillProject) => onCreated(p.id),
  });
  const [name, setName] = React.useState("");
  const [address, setAddress] = React.useState("");

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg bg-chrome rounded-t-3xl p-6 pb-[calc(env(safe-area-inset-bottom)+24px)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="w-10 h-1 bg-separator/60 rounded-full mx-auto mb-5" />
        <p className="text-headline font-semibold text-label-primary mb-4">New Project</p>
        <div className="mb-4">
          <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1.5">
            Project Name *
          </label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Columbus Data Center Phase 1"
            className="w-full rounded-xl px-4 py-3 text-body text-label-primary bg-bg-elevated border border-separator/60 placeholder:text-label-quaternary focus:outline-none focus:border-accent"
          />
        </div>
        <div className="mb-5">
          <label className="block text-footnote font-semibold text-label-secondary uppercase tracking-wide mb-1.5">
            Address
          </label>
          <input
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="3990 E Broad St, Columbus OH"
            className="w-full rounded-xl px-4 py-3 text-body text-label-primary bg-bg-elevated border border-separator/60 placeholder:text-label-quaternary focus:outline-none focus:border-accent"
          />
        </div>
        <button
          type="button"
          disabled={!name.trim() || createProject.isPending}
          onClick={() => createProject.mutate({ name: name.trim(), address: address.trim() || undefined })}
          className="w-full py-3.5 rounded-2xl font-semibold text-body bg-accent text-white disabled:opacity-60"
        >
          {createProject.isPending ? "Creating…" : "Create Project"}
        </button>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ProjectsPage() {
  const router = useRouter();
  const [showCreate, setShowCreate] = React.useState(false);
  const { data, isLoading, error } = useProjects();
  const projects = data?.items ?? [];

  return (
    <MobileShell>
      <TopBar
        title="Projects"
        right={
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1 text-accent font-semibold text-callout"
          >
            <Plus className="h-4 w-4" />
            New
          </button>
        }
      />

      {error && (
        <div className="px-4 pt-2">
          <ErrorBanner message="Failed to load projects." />
        </div>
      )}

      {!isLoading && projects.length === 0 && !error && (
        <div className="flex flex-col items-center justify-center px-6 pt-24 gap-4">
          <FolderKanban className="h-12 w-12 text-label-quaternary" />
          <div className="text-center">
            <p className="text-body font-semibold text-label-primary mb-1">No projects yet.</p>
            <p className="text-callout text-label-secondary">
              Create a project manually or advance a site evaluation.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="mt-2 flex items-center gap-2 bg-accent text-white font-semibold text-callout px-5 py-2.5 rounded-full"
          >
            <Plus className="h-4 w-4" />
            New Project
          </button>
        </div>
      )}

      {(isLoading || projects.length > 0) && (
        <div className="px-4 pt-3">
          {isLoading
            ? Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="rounded-2xl bg-chrome/80 border border-separator/40 h-28 mb-3 animate-pulse" />
              ))
            : projects.map((project) => (
                <ProjectCard
                  key={project.id}
                  project={project}
                  onClick={() => router.push(`/projects/${project.id}`)}
                />
              ))}
        </div>
      )}

      {/* FAB */}
      <button
        type="button"
        aria-label="New project"
        onClick={() => setShowCreate(true)}
        className={cn(
          "fixed bottom-[calc(env(safe-area-inset-bottom)+72px)] right-4",
          "h-14 w-14 rounded-full bg-accent shadow-lg shadow-accent/30",
          "flex items-center justify-center",
          "transition-transform active:scale-95",
        )}
      >
        <Plus className="h-6 w-6 text-white" strokeWidth={2.5} />
      </button>

      {showCreate && (
        <CreateProjectModal
          onClose={() => setShowCreate(false)}
          onCreated={(id) => {
            setShowCreate(false);
            router.push(`/projects/${id}`);
          }}
        />
      )}
    </MobileShell>
  );
}
