"use client";

import * as React from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AaceClassification } from "@/lib/schemas";
import { ArtifactCard, ArtifactCardBody, ArtifactCardHeader } from "./shared/ArtifactCard";
import { Section } from "./shared/Section";
import { CitationList } from "./shared/Citation";
import { ConfidenceBadge } from "./shared/Confidence";
import { MarkdownBlock } from "./shared/MarkdownBlock";

/** Accuracy range labels per AACE 18R-97 */
const AACE_ACCURACY: Record<string, { low: string; high: string }> = {
  "5": { low: "−50%", high: "+100%" },
  "4": { low: "−30%", high: "+50%" },
  "3": { low: "−20%", high: "+30%" },
  "2": { low: "−15%", high: "+20%" },
  "1": { low: "−10%", high: "+15%" },
};

export function AaceClassificationView({
  artifact,
  mode = "view",
}: {
  artifact: AaceClassification;
  mode?: "view" | "print";
}) {
  const meta = artifact.metadata;
  const cls = meta.class ?? "?";
  const accuracy = meta.accuracy_range
    ? {
        low: `${meta.accuracy_range.low_pct}%`,
        high: `+${meta.accuracy_range.high_pct}%`,
      }
    : AACE_ACCURACY[cls];

  const disciplines = meta.design_disciplines_detected ?? [];
  const allKnown = [
    "architectural",
    "structural",
    "mechanical",
    "electrical",
    "plumbing",
    "civil",
    "fire_protection",
    "mep",
  ];
  // Show detected disciplines vs not-detected for known disciplines
  const evidenceCategories = new Set(
    (meta.supporting_evidence ?? []).map((e) => e.category.toLowerCase()),
  );

  const citations = Array.isArray(artifact.citations)
    ? (artifact.citations as Array<{ kind?: string; ref?: string; note?: string; url?: string }>)
    : [];

  const isPrint = mode === "print";

  return (
    <div className="space-y-4">
      {/* ── Hero ── */}
      <ArtifactCard>
        <ArtifactCardHeader>
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="inline-flex items-center rounded-lg bg-accent px-3 py-1.5 text-title-3 font-bold text-white">
                  Class {cls}
                </span>
                {accuracy && (
                  <span className="text-callout text-label-secondary tabular-nums">
                    {accuracy.low} / {accuracy.high}
                  </span>
                )}
                <ConfidenceBadge confidence={artifact.confidence ?? 0} />
              </div>
              <div className="mt-1 text-footnote text-label-tertiary">
                {Math.round(meta.design_maturity_estimate_pct ?? 0)}% design
                maturity
              </div>
            </div>
          </div>
        </ArtifactCardHeader>
        <ArtifactCardBody>
          <p className="text-callout text-label-primary leading-relaxed">
            {artifact.summary}
          </p>
        </ArtifactCardBody>
      </ArtifactCard>

      {/* ── Discipline coverage pills ── */}
      {(disciplines.length > 0 || evidenceCategories.size > 0) && (
        <ArtifactCard>
          <ArtifactCardHeader>
            <div className="text-caption-1 uppercase tracking-wider text-label-tertiary">
              Disciplines detected
            </div>
          </ArtifactCardHeader>
          <ArtifactCardBody>
            <div className="flex flex-wrap gap-2">
              {allKnown.map((disc) => {
                const detected =
                  disciplines.includes(disc) ||
                  disciplines.includes(disc.replace("_", "-")) ||
                  evidenceCategories.has(disc) ||
                  evidenceCategories.has(`${disc}_detail`);
                return (
                  <span
                    key={disc}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-footnote",
                      detected
                        ? "bg-success/15 text-success"
                        : "bg-bg-elevated text-label-tertiary",
                    )}
                  >
                    {detected ? (
                      <CheckCircle2 className="h-3 w-3" aria-hidden />
                    ) : (
                      <XCircle className="h-3 w-3" aria-hidden />
                    )}
                    {disc.replace(/_/g, " ")}
                  </span>
                );
              })}
              {/* Any extra detected disciplines not in the known list */}
              {disciplines
                .filter(
                  (d) =>
                    !allKnown.includes(d) &&
                    !allKnown.includes(d.replace("-", "_")),
                )
                .map((d) => (
                  <span
                    key={d}
                    className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-footnote bg-success/15 text-success"
                  >
                    <CheckCircle2 className="h-3 w-3" aria-hidden />
                    {d.replace(/[_-]/g, " ")}
                  </span>
                ))}
            </div>
          </ArtifactCardBody>
        </ArtifactCard>
      )}

      {/* ── Supporting evidence scores ── */}
      {meta.supporting_evidence.length > 0 && (
        <Section
          title="Supporting evidence"
          defaultOpen={true}
          printForceOpen={isPrint}
        >
          <ul className="space-y-3 pt-1">
            {meta.supporting_evidence.map((ev, i) => (
              <li key={i} className="space-y-1">
                <div className="flex items-center gap-2">
                  <div className="h-1.5 flex-1 rounded-full bg-bg-tertiary overflow-hidden">
                    <div
                      className="h-full rounded-full bg-accent"
                      style={{ width: `${Math.round((ev.score ?? 0) * 100)}%` }}
                    />
                  </div>
                  <span className="text-caption-1 text-label-tertiary tabular-nums w-8 text-right">
                    {Math.round((ev.score ?? 0) * 100)}%
                  </span>
                </div>
                <div className="text-footnote text-label-secondary">
                  <span className="font-medium text-label-primary">
                    {prettyCategory(ev.category)}.
                  </span>{" "}
                  {ev.evidence}
                </div>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* ── Missing for next class ── */}
      {meta.missing_for_next_class.length > 0 && (
        <Section
          title={`To unlock the next class`}
          defaultOpen={true}
          printForceOpen={isPrint}
        >
          <ul className="space-y-3 pt-1">
            {meta.missing_for_next_class.map((m, i) => (
              <li key={i} className="rounded-lg bg-bg-tertiary px-3 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-callout font-medium text-label-primary">
                    {m.deliverable}
                  </div>
                  <span className="shrink-0 rounded-full bg-accent/15 px-2 py-0.5 text-caption-1 text-accent">
                    → Class {m.would_unlock_class}
                  </span>
                </div>
                {m.rationale && (
                  <div className="mt-1 text-footnote text-label-secondary">
                    {m.rationale}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* ── Body markdown ── */}
      {artifact.body_markdown && (
        <Section
          title="Full analysis"
          defaultOpen={false}
          printForceOpen={isPrint}
        >
          <MarkdownBlock content={artifact.body_markdown} className="pt-1" />
        </Section>
      )}

      {/* ── Uploaded files ── */}
      {meta.uploaded_files.length > 0 && (
        <Section
          title="Files reviewed"
          defaultOpen={false}
          printForceOpen={isPrint}
        >
          <ul className="space-y-2 pt-1">
            {meta.uploaded_files.map((f, i) => (
              <li
                key={i}
                className="flex items-start gap-2 text-footnote text-label-primary"
              >
                <span
                  className={cn(
                    "mt-0.5 inline-block rounded px-1.5 py-0.5 text-caption-2 font-mono uppercase",
                    f.extraction_status === "ok"
                      ? "bg-success/15 text-success"
                      : f.extraction_status === "partial"
                        ? "bg-warning/15 text-warning"
                        : "bg-danger/15 text-danger",
                  )}
                >
                  {f.extraction_status}
                </span>
                <div>
                  <div>{f.filename}</div>
                  {f.extraction_summary && (
                    <div className="text-label-tertiary mt-0.5">
                      {f.extraction_summary}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* ── Citations ── */}
      <CitationList citations={citations} />
    </div>
  );
}

function prettyCategory(cat: string): string {
  return cat
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
