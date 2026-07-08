"use client";

/**
 * /lifecycle — Portfolio lifecycle view.
 *
 * One screen that makes the whole capital-execution process walkable:
 *   - An onboarding banner explaining the lifecycle + total human decision
 *     points (so a new user instantly understands the model).
 *   - One card per project showing where it sits on the lifecycle strip, its
 *     open-approvals badge, and a tap-through to the project's full tracker.
 *
 * Companion to the per-project tracker on /projects/[id]. Both share
 * components/lifecycle/LifecycleTracker + lib/lifecycle.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { ChevronRight, ShieldCheck, Workflow, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { LifecycleStrip, LifecycleTracker } from "@/components/lifecycle/LifecycleTracker";
import {
  LIFECYCLE,
  projectStageIndex,
  totalHitlGates,
} from "@/lib/lifecycle";
import { useProjects, useApprovals } from "@/lib/api";
import type { QuillProject, ApprovalItem } from "@/lib/schemas";

// All workflow ids that belong to any lifecycle stage — used to attribute
// pending approvals to a project's lifecycle rather than generic queue items.
const LIFECYCLE_WORKFLOWS = new Set(LIFECYCLE.flatMap((s) => s.hitl.flatMap((h) => h.workflows)));

function projectOpenCount(_p: QuillProject, approvals: ApprovalItem[]): number {
  // Best-effort: approvals don't carry a project_id at the list level, so we
  // count pending lifecycle-workflow approvals portfolio-wide as the headline.
  return approvals.filter((a) => a.status === "pending" && LIFECYCLE_WORKFLOWS.has(a.workflow)).length;
}

function OnboardingBanner({ openTotal }: { openTotal: number }) {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="rounded-2xl border border-accent/20 bg-accent/[0.06] p-4 mb-4">
      <div className="flex items-start gap-3">
        <Workflow className="h-5 w-5 text-accent shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          <p className="text-callout font-semibold text-label-primary">How a project moves through Quill</p>
          <p className="text-caption-1 text-label-secondary mt-1">
            Every project flows through {LIFECYCLE.length} stages, from origination to live operations.
            Agents do the administrative work; you approve what commits the business. There are{" "}
            <span className="font-semibold text-label-primary">{totalHitlGates()} human decision points</span>{" "}
            across the full lifecycle.
          </p>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="mt-2 inline-flex items-center gap-1 text-caption-1 font-medium text-accent hover:underline"
          >
            <Info className="h-3.5 w-3.5" /> {open ? "Hide" : "Show"} the full lifecycle map
          </button>
        </div>
        {openTotal > 0 && (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 text-amber-400 text-caption-1 font-semibold px-2 py-1 shrink-0">
            <ShieldCheck className="h-3.5 w-3.5" /> {openTotal} waiting
          </span>
        )}
      </div>
      {open && (
        <div className="mt-3 border-t border-separator/30 pt-3">
          <LifecycleTracker phase="site_control" status="reference" approvals={[]} />
          <p className="text-caption-2 text-label-quaternary mt-2">
            Reference map — expand any stage to see its deliverables, agents, and decision points.
          </p>
        </div>
      )}
    </div>
  );
}

function statusBadge(status: string): { label: string; cls: string } {
  switch (status) {
    case "complete":
      return { label: "Complete", cls: "bg-accent/15 text-accent" };
    case "on_hold":
      return { label: "On hold", cls: "bg-amber-500/15 text-amber-400" };
    case "cancelled":
      return { label: "Cancelled", cls: "bg-red-500/15 text-red-400" };
    default:
      return { label: "Active", cls: "bg-white/[0.06] text-label-secondary" };
  }
}

function ProjectLifecycleCard({
  project,
  openCount,
  onOpen,
}: {
  project: QuillProject;
  openCount: number;
  onOpen: () => void;
}) {
  const idx = projectStageIndex(project.phase, project.status);
  const stage = LIFECYCLE[idx];
  const sb = statusBadge(project.status);
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "w-full text-left rounded-2xl p-4 mb-3",
        "bg-chrome/80 border border-separator/40 backdrop-blur-sm",
        "transition-all active:scale-[0.98] hover:border-separator/80",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-callout font-semibold text-label-primary truncate">{project.name}</p>
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            <span className={cn("text-caption-1 font-semibold rounded-full px-2 py-0.5", sb.cls)}>
              {sb.label}
            </span>
            <span className="text-caption-1 text-label-secondary">{stage?.label}</span>
            {openCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 text-amber-400 text-caption-1 font-semibold px-2 py-0.5">
                <ShieldCheck className="h-3 w-3" /> {openCount}
              </span>
            )}
          </div>
        </div>
        <ChevronRight className="h-4 w-4 text-label-quaternary shrink-0 mt-0.5" />
      </div>
      <div className="mt-3">
        <LifecycleStrip phase={project.phase} status={project.status} onSelect={() => onOpen()} />
      </div>
    </button>
  );
}

export default function LifecyclePage() {
  const router = useRouter();
  const { data, isLoading, error } = useProjects();
  const { data: approvals } = useApprovals();
  const projects = data?.items ?? [];
  const openApprovals = React.useMemo(
    () => (approvals ?? []).filter((a) => a.status === "pending"),
    [approvals],
  );
  const openTotal = openApprovals.filter((a) => LIFECYCLE_WORKFLOWS.has(a.workflow)).length;

  return (
    <MobileShell>
      <TopBar title="Lifecycle" subtitle="Where every project sits in capital execution" />
      <div className="px-4 pb-24">
        <OnboardingBanner openTotal={openTotal} />

        {error && <ErrorBanner message="Couldn't load projects." />}

        {isLoading && (
          <p className="text-callout text-label-tertiary py-8 text-center">Loading projects…</p>
        )}

        {!isLoading && !error && projects.length === 0 && (
          <EmptyState
            title="No projects yet"
            subtitle="Once you advance a site to a project, it will appear here on the lifecycle."
          />
        )}

        {projects.map((p) => (
          <ProjectLifecycleCard
            key={p.id}
            project={p}
            openCount={projectOpenCount(p, openApprovals)}
            onOpen={() => router.push(`/projects/${p.id}`)}
          />
        ))}
      </div>
    </MobileShell>
  );
}
