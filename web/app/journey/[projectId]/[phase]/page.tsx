"use client";

/**
 * /journey/[projectId]/[phase] — journey phase detail (Lovable redesign).
 *
 * SCAFFOLD (2026-07-18): renders the phase's milestone checklist + step body
 * derived from lib/journey.ts, wired to prod's useProject. The richer
 * interactions (step-scoped RequestInput composer, AgentChips, supporting
 * modules) are ported in the module pass; this scaffold already gives a
 * valid, navigable, on-brand screen so the home journey links never 404.
 */

import * as React from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Check, ChevronRight, Loader2 } from "lucide-react";
import { MobileShell } from "@/components/layout/MobileShell";
import {
  findPhase,
  phaseStatus,
  stepStatus,
  JOURNEY,
  type JourneyPhaseKey,
} from "@/lib/journey";
import { useProject } from "@/lib/api";
import { cn } from "@/lib/utils";

const PHASE_KEYS: JourneyPhaseKey[] = ["site", "estimate", "contract", "project", "operate"];

function isJourneyPhaseKey(v: string): v is JourneyPhaseKey {
  return (PHASE_KEYS as string[]).includes(v);
}

export default function PhaseDetailPage() {
  const params = useParams<{ projectId: string; phase: string }>();
  const projectId = params.projectId;
  const phaseKey: JourneyPhaseKey = isJourneyPhaseKey(params.phase) ? params.phase : "site";
  const { data: project, isLoading } = useProject(projectId);

  const journeyPhase = findPhase(phaseKey);
  const steps = journeyPhase.steps;

  const [selectedIdx, setSelectedIdx] = React.useState(0);
  React.useEffect(() => {
    if (!project) return;
    const currentIdx = steps.findIndex(
      (_, i) => stepStatus(phaseKey, i, project) === "current",
    );
    setSelectedIdx(currentIdx >= 0 ? currentIdx : 0);
  }, [project, phaseKey, steps]);

  if (isLoading || !project) {
    return (
      <MobileShell>
        <div className="flex min-h-[60vh] items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-label-tertiary" />
        </div>
      </MobileShell>
    );
  }

  const overallStatus = phaseStatus(phaseKey, project);
  const phaseIdx = PHASE_KEYS.indexOf(phaseKey);
  const prevPhase = phaseIdx > 0 ? PHASE_KEYS[phaseIdx - 1] : null;
  const nextPhase = phaseIdx < PHASE_KEYS.length - 1 ? PHASE_KEYS[phaseIdx + 1] : null;
  const selectedStep = steps[selectedIdx]!;

  return (
    <MobileShell>
      <header className="bg-bg pt-safe sticky top-0 z-30">
        <div className="mx-auto w-full max-w-[708px] px-4 pt-2 pb-3 md:max-w-4xl md:px-8">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <h1 className="text-large-title font-bold text-label-primary">
                {journeyPhase.label}
              </h1>
              <p className="text-subhead mt-0.5 text-label-secondary">
                {project.name} ·{" "}
                {overallStatus === "complete"
                  ? "Complete"
                  : overallStatus === "current"
                    ? "In progress"
                    : "Upcoming"}
              </p>
            </div>
            <div className="mt-1 flex items-center gap-2">
              {prevPhase && (
                <Link
                  href={`/journey/${encodeURIComponent(projectId)}/${prevPhase}`}
                  aria-label={`Previous phase: ${findPhase(prevPhase).label}`}
                  className="no-tap-highlight ease-ios flex h-7 w-7 items-center justify-center rounded-full bg-bg-elevated text-label-secondary shadow-card active:scale-[0.96] duration-tap"
                >
                  <ChevronRight className="h-4 w-4 rotate-180" strokeWidth={2.4} />
                </Link>
              )}
              {nextPhase && (
                <Link
                  href={`/journey/${encodeURIComponent(projectId)}/${nextPhase}`}
                  aria-label={`Next phase: ${findPhase(nextPhase).label}`}
                  className="no-tap-highlight ease-ios inline-flex items-center gap-1.5 rounded-full bg-bg-elevated py-1 pr-1 pl-3 shadow-card active:scale-[0.98] duration-tap"
                >
                  <span className="text-caption-1 font-semibold text-label-primary">
                    {findPhase(nextPhase).label}
                  </span>
                  <span className="flex h-[22px] w-[22px] items-center justify-center rounded-full bg-accent text-white">
                    <ChevronRight className="h-3.5 w-3.5" strokeWidth={2.6} />
                  </span>
                </Link>
              )}
            </div>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-[708px] px-4 pt-4 pb-home md:max-w-4xl md:px-8">
        <section aria-label="Milestones" className="space-y-2">
          <p className="text-caption-1 mb-1.5 ml-1 font-semibold uppercase tracking-wide text-label-tertiary">
            Milestones ·{" "}
            {steps.filter((_, i) => stepStatus(phaseKey, i, project) === "complete").length}/
            {steps.length}
          </p>
          <div className="ios-list-group">
            {steps.map((s, i) => {
              const st = stepStatus(phaseKey, i, project);
              const isLast = i === steps.length - 1;
              const statusLabel =
                st === "complete" ? "Delivered" : st === "current" ? "In progress" : "Not started";
              return (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => setSelectedIdx(i)}
                  aria-current={st === "current" ? "step" : undefined}
                  aria-pressed={i === selectedIdx}
                  className={cn(
                    "ios-list-row no-tap-highlight ease-ios w-full text-left active:scale-[0.995] duration-tap",
                    isLast && "ios-list-row-last",
                    i === selectedIdx && "bg-accent-tint",
                  )}
                >
                  <span
                    aria-hidden
                    className={cn(
                      "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-footnote font-semibold",
                      st === "complete"
                        ? "bg-success text-white"
                        : st === "current"
                          ? "border-2 border-accent bg-bg text-accent"
                          : "border border-hairline bg-bg text-label-tertiary",
                    )}
                  >
                    {st === "complete" ? <Check className="h-4 w-4" strokeWidth={2.8} /> : i + 1}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-headline font-semibold text-label-primary">
                      {s.label}
                    </span>
                    <span className="mt-0.5 block truncate text-footnote text-label-secondary">
                      {s.description}
                    </span>
                    <span className="mt-1 flex items-center gap-1.5 text-caption-1">
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full px-2 py-0.5 font-semibold",
                          st === "complete"
                            ? "bg-success/[0.12] text-success"
                            : st === "current"
                              ? "bg-accent/[0.12] text-accent"
                              : "bg-bg-elevated text-label-tertiary",
                        )}
                      >
                        {statusLabel}
                      </span>
                      <span className="truncate text-label-tertiary">· {s.deliverable}</span>
                    </span>
                  </span>
                  <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-label-quaternary" />
                </button>
              );
            })}
          </div>
        </section>

        <section aria-label="Step" className="mt-5 space-y-4">
          <div>
            <h2 className="text-title-2 font-bold text-label-primary">{selectedStep.label}</h2>
            <p className="mt-1 text-callout text-label-secondary">{selectedStep.description}</p>
          </div>
          <Link
            href={selectedStep.target({ id: projectId }).href}
            className="no-tap-highlight flex items-center gap-3 rounded-2xl bg-bg-elevated border border-hairline p-4 shadow-card active:scale-[0.99] transition-transform"
          >
            <div className="min-w-0 flex-1">
              <p className="text-title-3 font-semibold text-label-primary truncate">
                {selectedStep.deliverable}
              </p>
              <p className="text-subhead text-label-secondary">Open module</p>
            </div>
            <ChevronRight className="h-5 w-5 shrink-0 text-label-tertiary" strokeWidth={1.8} />
          </Link>
          <div className="flex flex-wrap gap-2">
            {selectedStep.agents.map((a) => (
              <span
                key={a}
                className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-bg-elevated px-3 py-1.5 text-footnote shadow-card text-label-primary font-medium"
              >
                {a}
              </span>
            ))}
          </div>
        </section>
      </div>
    </MobileShell>
  );
}
