"use client";

import * as React from "react";
import { ChevronDown, Sparkles, AlertTriangle } from "lucide-react";
import { MarkdownBody } from "@/components/documents/MarkdownBody";
import { cn } from "@/lib/utils";
import type { ChainOutputs, ChainStepOutput } from "@/lib/schemas";

/**
 * ChainOutputsPanel — renders the structured `chain_outputs` blob that
 * the TriageDispatcher (Phase F.1) attaches to chained queue items.
 *
 * Two collapsible sections, both open by default so Charles sees the draft
 * the moment he taps in:
 *   1. "Triage classification" — shows discipline, priority, related specs,
 *      escalations from the first agent's output (rfi-triage / submittal-
 *      triage / etc.). Renders as a label/value table.
 *   2. "Draft response" — the second agent's `draft_markdown` (rfi-drafter
 *      output) rendered through react-markdown with sanitization.
 *
 * Section ordering follows the order steps appear in `chain_outputs.steps`
 * with a small heuristic: the FIRST classification-shaped step becomes the
 * Triage panel, the FIRST draft-shaped step becomes the Draft panel. Other
 * steps are rendered as generic collapsible JSON below.
 */
export function ChainOutputsPanel({ chain }: { chain: ChainOutputs }) {
  const triageStep = chain.steps.find((s) => isTriageStep(s));
  const draftStep = chain.steps.find((s) => isDraftStep(s));
  const otherSteps = chain.steps.filter(
    (s) => s !== triageStep && s !== draftStep,
  );

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2 px-1">
        <span className="text-caption-1 uppercase tracking-wider text-label-secondary">
          Live draft
        </span>
        <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
        <span className="text-caption-1 text-label-tertiary">
          {chain.chain_id}
        </span>
      </div>

      {triageStep && (
        <CollapsibleSection
          title="Triage classification"
          subtitle={triageStep.agent_id}
          defaultOpen
        >
          <TriageBlock step={triageStep} />
        </CollapsibleSection>
      )}

      {draftStep && (
        <CollapsibleSection
          title="Draft response"
          subtitle={draftStep.agent_id}
          defaultOpen
          accent={
            draftStep.confidence != null && draftStep.confidence < 0.7
              ? "warning"
              : undefined
          }
        >
          <DraftBlock step={draftStep} />
        </CollapsibleSection>
      )}

      {otherSteps.length > 0 && (
        <CollapsibleSection title="Other agent outputs">
          <div className="space-y-3">
            {otherSteps.map((s, i) => (
              <div key={i} className="rounded-md bg-bg-elevated/40 p-3">
                <div className="text-footnote text-label-secondary mb-1">
                  {s.agent_id} {s.ok ? "" : "· error"}
                </div>
                <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-caption-1 text-label-primary">
                  {JSON.stringify(s.output ?? s.error ?? null, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

      {(chain.skipped?.length ?? 0) > 0 && (
        <div className="rounded-md bg-bg-elevated px-3 py-2 text-caption-1 text-label-secondary">
          <span className="font-medium text-label-primary">Skipped:</span>{" "}
          {chain.skipped!.join(", ")} (gated by upstream confidence /
          escalations)
        </div>
      )}

      {(chain.errors?.length ?? 0) > 0 && (
        <div className="flex gap-2 rounded-md bg-warning-soft px-3 py-2 text-caption-1 text-label-primary">
          <AlertTriangle
            className="h-3.5 w-3.5 shrink-0 text-warning"
            aria-hidden="true"
          />
          <div>
            <div className="font-medium">Chain warnings</div>
            <ul className="ml-3 list-disc">
              {chain.errors!.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}

/* ── Helpers ──────────────────────────────────────────────────────────── */

function isTriageStep(s: ChainStepOutput): boolean {
  if (s.agent_id.includes("triage")) return true;
  const out = s.output ?? {};
  return (
    "discipline" in out ||
    "category" in out ||
    "priority" in out ||
    "spec_section" in out
  );
}

function isDraftStep(s: ChainStepOutput): boolean {
  if (s.agent_id.includes("drafter") || s.agent_id.includes("draft")) {
    return true;
  }
  const out = s.output ?? {};
  return (
    "draft_markdown" in out ||
    "draft_response" in out ||
    "response_markdown" in out
  );
}

function getDraftMarkdown(step: ChainStepOutput): string | null {
  const out = step.output ?? {};
  for (const key of [
    "draft_markdown",
    "response_markdown",
    "draft_response",
    "draft",
    "response",
  ]) {
    const v = (out as Record<string, unknown>)[key];
    if (typeof v === "string" && v.trim().length > 0) return v;
  }
  return null;
}

/* ── Sub-components ───────────────────────────────────────────────────── */

function CollapsibleSection({
  title,
  subtitle,
  defaultOpen = false,
  accent,
  children,
}: {
  title: string;
  subtitle?: string;
  defaultOpen?: boolean;
  accent?: "warning" | "danger";
  children: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <section
      className={cn(
        "rounded-xl bg-bg-elevated overflow-hidden",
        accent === "warning" && "ring-1 ring-warning/40",
        accent === "danger" && "ring-1 ring-danger/40",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-4 py-3 min-h-[44px] active:bg-bg-tertiary/40 no-tap-highlight"
      >
        <span className="flex items-center gap-2">
          <span className="text-callout text-label-primary font-medium">
            {title}
          </span>
          {subtitle && (
            <span className="text-caption-1 text-label-tertiary">
              {subtitle}
            </span>
          )}
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-label-tertiary transition-transform",
            open && "rotate-180",
          )}
          aria-hidden="true"
        />
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </section>
  );
}

function TriageBlock({ step }: { step: ChainStepOutput }) {
  if (!step.ok || !step.output) {
    return (
      <p className="text-callout text-label-secondary italic">
        Triage agent didn’t return a clean classification.
        {step.error ? ` (${step.error})` : null}
      </p>
    );
  }
  const out = step.output as Record<string, unknown>;
  const rows: Array<[string, string]> = [];

  // Pull the keys we know about (in display order). Anything else falls into
  // an "Other" bucket.
  const knownOrder = [
    "discipline",
    "category",
    "priority",
    "spec_section",
    "spec_sections",
    "related_specs",
    "drawing_id",
    "subcontractor",
    "building",
    "suggested_assignee",
    "summary",
  ];
  for (const k of knownOrder) {
    const v = out[k];
    if (v == null) continue;
    rows.push([prettyLabel(k), prettyValue(v)]);
  }
  // Confidence shown in its own row.
  if (step.confidence != null) {
    rows.push(["Confidence", `${Math.round(step.confidence * 100)}%`]);
  }

  const escalations = (out.escalations as unknown) || [];
  const escalationList = Array.isArray(escalations)
    ? (escalations as string[])
    : [];

  return (
    <div className="space-y-3">
      {rows.length > 0 && (
        <dl className="grid grid-cols-1 gap-y-1">
          {rows.map(([k, v]) => (
            <div
              key={k}
              className="flex items-baseline justify-between gap-3 text-callout"
            >
              <dt className="text-label-secondary">{k}</dt>
              <dd className="text-label-primary text-right break-words max-w-[60%]">
                {v}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {escalationList.length > 0 && (
        <div>
          <div className="text-caption-1 uppercase tracking-wider text-label-tertiary mb-1">
            Escalations
          </div>
          <ul className="ml-4 list-disc text-callout text-label-primary">
            {escalationList.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function DraftBlock({ step }: { step: ChainStepOutput }) {
  if (!step.ok) {
    return (
      <p className="text-callout text-label-secondary italic">
        Drafter agent didn’t produce a draft.
        {step.error ? ` (${step.error})` : null}
      </p>
    );
  }
  const md = getDraftMarkdown(step);
  if (!md) {
    return (
      <p className="text-callout text-label-secondary italic">
        Drafter agent returned a structured object but no markdown body.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <MarkdownBody markdown={md} />
      {step.confidence != null && (
        <div className="text-footnote text-label-tertiary">
          Drafter confidence: {Math.round(step.confidence * 100)}%
        </div>
      )}
    </div>
  );
}

function prettyLabel(k: string): string {
  return k
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function prettyValue(v: unknown): string {
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.join(", ");
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}
