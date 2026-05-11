"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { AlertTriangle } from "lucide-react";
import type { ContractInterpretation } from "@/lib/schemas";
import { ArtifactCard, ArtifactCardBody, ArtifactCardHeader } from "./shared/ArtifactCard";
import { MarkdownBlock } from "./shared/MarkdownBlock";

const _DISCLAIMER =
  "AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision.";

function ConfidenceBar({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const colorClass =
    pct >= 80
      ? "bg-green-500"
      : pct >= 60
      ? "bg-amber-400"
      : pct >= 40
      ? "bg-orange-400"
      : "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-bg-tertiary overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", colorClass)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-caption text-label-tertiary tabular-nums">{pct}%</span>
    </div>
  );
}

/**
 * ContractInterpretationView — renders a single Q&A pair.
 * Used in the Ask tab list AND standalone as an artifact view.
 *
 * When `compact=true` shows a minimal card without the hero layout.
 */
export function ContractInterpretationView({
  item,
  compact = false,
  mode = "view",
}: {
  item: ContractInterpretation;
  compact?: boolean;
  mode?: "view" | "print";
}) {
  const isPrint = mode === "print";
  const clauses = Array.isArray(item.supporting_clauses) ? item.supporting_clauses : [];
  const caveats = Array.isArray(item.caveats) ? item.caveats : [];
  const disclaimer = typeof item.disclaimer === "string" ? item.disclaimer : _DISCLAIMER;

  if (compact) {
    return (
      <div className="space-y-2 py-3 border-b border-separator last:border-0">
        {/* Question */}
        <p className="text-callout font-semibold text-label-primary">{item.question}</p>

        {/* Answer */}
        <div className="text-footnote text-label-primary leading-relaxed">
          <MarkdownBlock content={item.answer} />
        </div>

        {/* Confidence */}
        <div>
          <p className="text-caption text-label-tertiary mb-1">Confidence</p>
          <ConfidenceBar confidence={item.confidence} />
        </div>

        {/* Supporting clauses */}
        {clauses.length > 0 && (
          <div>
            <p className="text-caption text-label-tertiary font-medium mb-1">
              Supporting Clauses
            </p>
            <div className="space-y-1">
              {clauses.map((c: any, i: number) => (
                <div key={i} className="rounded bg-bg-tertiary px-2 py-1.5">
                  <p className="text-caption text-label-tertiary">{c.location}</p>
                  <p className="text-caption italic text-label-secondary leading-relaxed">
                    "{c.verbatim}"
                  </p>
                  {c.why_relevant && (
                    <p className="text-caption text-label-secondary mt-0.5">{c.why_relevant}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Caveats */}
        {caveats.length > 0 && (
          <div>
            <p className="text-caption text-label-tertiary font-medium mb-1">Caveats</p>
            <ul className="space-y-1">
              {caveats.map((c: any, i: number) => (
                <li key={i} className="flex items-start gap-1">
                  <span className="text-label-tertiary text-caption">•</span>
                  <span className="text-caption text-label-secondary">{c.caveat}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Disclaimer */}
        <div className="flex items-start gap-1.5 text-caption text-amber-700">
          <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0 text-amber-500" aria-hidden="true" />
          <span className="text-xs">{disclaimer}</span>
        </div>
      </div>
    );
  }

  // Full card layout (standalone artifact view)
  return (
    <div className="space-y-3">
      {/* ── Disclaimer ── */}
      <div className="flex items-start gap-2 rounded-xl bg-amber-50 border border-amber-200 px-3 py-2.5 text-caption text-amber-800">
        <AlertTriangle
          className="h-4 w-4 mt-0.5 shrink-0 text-amber-500"
          aria-hidden="true"
        />
        <span>{disclaimer}</span>
      </div>

      {/* ── Q&A Card ── */}
      <ArtifactCard>
        <ArtifactCardHeader>
          <p className="text-callout font-semibold text-label-primary mb-1">
            {item.question}
          </p>
        </ArtifactCardHeader>
        <ArtifactCardBody>
          <div className="text-footnote text-label-primary leading-relaxed mb-3">
            <MarkdownBlock content={item.answer} />
          </div>

          {/* Confidence */}
          <div className="mb-3">
            <p className="text-caption text-label-tertiary mb-1.5">Answer Confidence</p>
            <ConfidenceBar confidence={item.confidence} />
          </div>
        </ArtifactCardBody>
      </ArtifactCard>

      {/* ── Supporting Clauses ── */}
      {clauses.length > 0 && (
        <div className="rounded-xl bg-bg-elevated overflow-hidden">
          <p className="px-4 py-3 text-callout font-semibold text-label-primary border-b border-separator">
            Supporting Clauses
          </p>
          <div className="px-4 pb-3 pt-2 space-y-2">
            {clauses.map((c: any, i: number) => (
              <div
                key={i}
                className="rounded-lg bg-bg-tertiary px-3 py-2 space-y-1"
              >
                <p className="text-caption text-accent font-medium">{c.location}</p>
                <blockquote className="text-caption italic text-label-secondary leading-relaxed border-l-2 border-separator pl-2">
                  "{c.verbatim}"
                </blockquote>
                {c.why_relevant && (
                  <p className="text-caption text-label-secondary">
                    {c.why_relevant}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Caveats ── */}
      {caveats.length > 0 && (
        <div className="rounded-xl bg-bg-elevated overflow-hidden">
          <p className="px-4 py-3 text-callout font-semibold text-label-primary border-b border-separator">
            Caveats
          </p>
          <ul className="px-4 pb-3 pt-2 space-y-1.5">
            {caveats.map((c: any, i: number) => (
              <li key={i} className="flex items-start gap-2">
                <span className="text-amber-400 shrink-0 mt-0.5">⚠</span>
                <span className="text-caption text-label-secondary leading-relaxed">
                  {c.caveat}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
