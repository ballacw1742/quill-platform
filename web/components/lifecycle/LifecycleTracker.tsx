"use client";

/**
 * LifecycleTracker — the shared project-lifecycle visualization.
 *
 * Renders the full capital-execution lifecycle (Origination → 6 project phases
 * → Operations) as a walkable, drill-downable tracker. Used in two places:
 *   1. Per-project (compact=false, projectId set, phase highlighted)
 *   2. Portfolio /lifecycle page (one row per project via LifecycleRow)
 *
 * Each stage node shows deliverables, engaged agents, and a badge for OPEN
 * human-in-the-loop approvals whose workflow belongs to that stage — so a user
 * instantly sees "what's waiting on me here." Clicking a stage drills into the
 * relevant module records.
 *
 * Design: dark Quill theme, iOS-style cards, accent highlight for current
 * stage — matches the existing /projects and /contracts patterns.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { Check, ChevronRight, Bot, FileOutput, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  LIFECYCLE,
  laneLabel,
  projectStageIndex,
  resolveHref,
  type LifecycleStage,
} from "@/lib/lifecycle";
import type { ApprovalItem } from "@/lib/schemas";

// Count OPEN (pending) approvals whose workflow belongs to a given stage.
function openApprovalsForStage(stage: LifecycleStage, approvals: ApprovalItem[]): number {
  if (!stage.hitl.length || !approvals?.length) return 0;
  const wf = new Set(stage.hitl.flatMap((h) => h.workflows));
  if (!wf.size) return 0;
  return approvals.filter(
    (a) => a.status === "pending" && wf.has(a.workflow),
  ).length;
}

type NodeState = "done" | "active" | "future";

function StageDot({ state, index }: { state: NodeState; index: number }) {
  return (
    <div
      className={cn(
        "w-7 h-7 rounded-full border-2 flex items-center justify-center shrink-0 text-caption-1 font-bold transition-colors",
        state === "done" && "border-accent bg-accent text-white",
        state === "active" && "border-accent bg-accent/15 text-accent",
        state === "future" && "border-separator/40 bg-transparent text-label-quaternary",
      )}
    >
      {state === "done" ? <Check className="h-4 w-4" /> : index + 1}
    </div>
  );
}

// ── Full per-project tracker (vertical, expandable) ─────────────────────────

export function LifecycleTracker({
  phase,
  status,
  projectId,
  approvals = [],
}: {
  phase: string;
  status?: string;
  projectId?: string;
  approvals?: ApprovalItem[];
}) {
  const router = useRouter();
  const currentIdx = projectStageIndex(phase, status);
  const [expanded, setExpanded] = React.useState<string | null>(
    LIFECYCLE[currentIdx]?.key ?? null,
  );

  return (
    <div className="space-y-1">
      {LIFECYCLE.map((stage, i) => {
        const state: NodeState =
          i < currentIdx ? "done" : i === currentIdx ? "active" : "future";
        const isOpen = expanded === stage.key;
        const openCount = openApprovalsForStage(stage, approvals);

        return (
          <div key={stage.key}>
            <button
              type="button"
              onClick={() => setExpanded(isOpen ? null : stage.key)}
              className={cn(
                "w-full flex items-center gap-3 py-2.5 px-2 rounded-xl text-left transition-colors",
                isOpen ? "bg-white/[0.04]" : "hover:bg-white/[0.02]",
              )}
            >
              <StageDot state={state} index={i} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "text-callout",
                      state === "done" && "text-label-secondary",
                      state === "active" && "text-label-primary font-semibold",
                      state === "future" && "text-label-quaternary",
                    )}
                  >
                    {stage.label}
                  </span>
                  {!stage.isProjectPhase && (
                    <span className="text-caption-2 text-label-quaternary uppercase tracking-wide">
                      {stage.key === "origination" ? "pre-project" : "post-project"}
                    </span>
                  )}
                  {state === "active" && (
                    <span className="text-caption-1 font-semibold text-accent">Current</span>
                  )}
                  {openCount > 0 && (
                    <span
                      className="ml-1 inline-flex items-center gap-1 rounded-full bg-amber-500/15 text-amber-400 text-caption-1 font-semibold px-2 py-0.5"
                      title={`${openCount} approval(s) waiting`}
                    >
                      <ShieldCheck className="h-3 w-3" />
                      {openCount}
                    </span>
                  )}
                </div>
                <p className="text-caption-1 text-label-quaternary truncate">{stage.blurb}</p>
              </div>
              <ChevronRight
                className={cn(
                  "h-4 w-4 text-label-quaternary transition-transform shrink-0",
                  isOpen && "rotate-90",
                )}
              />
            </button>

            {isOpen && (
              <div className="ml-10 mb-2 mt-1 space-y-3 rounded-xl border border-separator/30 bg-black/20 p-3">
                {/* Deliverables */}
                <div>
                  <div className="flex items-center gap-1.5 text-caption-1 font-semibold text-label-secondary mb-1">
                    <FileOutput className="h-3.5 w-3.5" /> Deliverables
                  </div>
                  <ul className="space-y-0.5">
                    {stage.deliverables.map((d) => (
                      <li key={d} className="text-caption-1 text-label-tertiary flex gap-1.5">
                        <span className="text-accent">•</span> {d}
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Agents */}
                <div>
                  <div className="flex items-center gap-1.5 text-caption-1 font-semibold text-label-secondary mb-1">
                    <Bot className="h-3.5 w-3.5" /> Agents engaged
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {stage.agents.map((a) => (
                      <span
                        key={a}
                        className="text-caption-2 text-label-tertiary bg-white/[0.04] rounded-md px-1.5 py-0.5"
                      >
                        {a}
                      </span>
                    ))}
                  </div>
                </div>

                {/* HITL gates */}
                <div>
                  <div className="flex items-center gap-1.5 text-caption-1 font-semibold text-label-secondary mb-1">
                    <ShieldCheck className="h-3.5 w-3.5" /> Human decision points ({stage.hitl.length})
                  </div>
                  <ul className="space-y-1">
                    {stage.hitl.map((h) => (
                      <li key={h.label} className="flex items-center gap-2 text-caption-1">
                        <span className="text-label-tertiary flex-1">{h.label}</span>
                        <span
                          className={cn(
                            "text-caption-2 rounded px-1.5 py-0.5 font-medium",
                            h.lane === 3 && "bg-red-500/15 text-red-400",
                            h.lane === 2 && "bg-accent/15 text-accent",
                            h.lane === 1 && "bg-white/[0.06] text-label-quaternary",
                          )}
                        >
                          {laneLabel(h.lane)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Drill-down links */}
                {stage.drilldown && stage.drilldown.length > 0 && (
                  <div className="flex flex-wrap gap-2 pt-1">
                    {stage.drilldown.map((d) => (
                      <button
                        key={d.href}
                        type="button"
                        onClick={() => router.push(resolveHref(d.href, projectId))}
                        className="inline-flex items-center gap-1 text-caption-1 font-medium text-accent hover:underline"
                      >
                        {d.label} <ChevronRight className="h-3 w-3" />
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Compact horizontal strip (portfolio row / project header) ───────────────

export function LifecycleStrip({
  phase,
  status,
  onSelect,
}: {
  phase: string;
  status?: string;
  onSelect?: (stageKey: string) => void;
}) {
  const currentIdx = projectStageIndex(phase, status);
  return (
    <div className="flex items-center gap-1 overflow-x-auto no-scrollbar py-1">
      {LIFECYCLE.map((stage, i) => {
        const state: NodeState =
          i < currentIdx ? "done" : i === currentIdx ? "active" : "future";
        return (
          <React.Fragment key={stage.key}>
            {i > 0 && (
              <div
                className={cn(
                  "h-0.5 w-4 shrink-0 rounded-full",
                  i <= currentIdx ? "bg-accent" : "bg-separator/40",
                )}
              />
            )}
            <button
              type="button"
              onClick={() => onSelect?.(stage.key)}
              title={`${stage.label} — ${stage.blurb}`}
              className={cn(
                "shrink-0 flex items-center gap-1.5 rounded-full px-2 py-1 text-caption-2 transition-colors",
                state === "active" && "bg-accent/15 text-accent font-semibold",
                state === "done" && "text-label-secondary hover:bg-white/[0.04]",
                state === "future" && "text-label-quaternary hover:bg-white/[0.02]",
              )}
            >
              <span
                className={cn(
                  "w-2 h-2 rounded-full shrink-0",
                  state === "done" && "bg-accent",
                  state === "active" && "bg-accent ring-2 ring-accent/30",
                  state === "future" && "bg-separator/50",
                )}
              />
              {stage.label}
            </button>
          </React.Fragment>
        );
      })}
    </div>
  );
}
