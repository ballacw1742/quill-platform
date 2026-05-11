"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { AlertTriangle, CheckCircle, XCircle, Info } from "lucide-react";
import type {
  ContractReviewMetadata,
  ContractRiskFlag,
  ContractMissingProtection,
  MarketTermsEntry,
} from "@/lib/schemas";
import {
  ArtifactCard,
  ArtifactCardBody,
  ArtifactCardHeader,
} from "./shared/ArtifactCard";
import { Section } from "./shared/Section";

const _DISCLAIMER =
  "AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision.";

// ── Severity config ───────────────────────────────────────────────────────
const SEVERITY_CONFIG = {
  critical: {
    label: "Critical",
    bgClass: "bg-red-100",
    textClass: "text-red-700",
    borderClass: "border-red-200",
    dotClass: "bg-red-500",
  },
  high: {
    label: "High",
    bgClass: "bg-orange-100",
    textClass: "text-orange-700",
    borderClass: "border-orange-200",
    dotClass: "bg-orange-500",
  },
  medium: {
    label: "Medium",
    bgClass: "bg-amber-100",
    textClass: "text-amber-700",
    borderClass: "border-amber-200",
    dotClass: "bg-amber-500",
  },
  low: {
    label: "Low",
    bgClass: "bg-blue-50",
    textClass: "text-blue-700",
    borderClass: "border-blue-100",
    dotClass: "bg-blue-400",
  },
  info: {
    label: "Info",
    bgClass: "bg-gray-50",
    textClass: "text-gray-600",
    borderClass: "border-gray-100",
    dotClass: "bg-gray-400",
  },
};

// ── Verdict config ────────────────────────────────────────────────────────
const VERDICT_CONFIG: Record<
  string,
  { label: string; className: string }
> = {
  "in-market": {
    label: "In-market",
    className: "text-green-700 bg-green-50",
  },
  "off-market-favorable": {
    label: "Favorable",
    className: "text-blue-700 bg-blue-50",
  },
  "off-market-unfavorable": {
    label: "Unfavorable",
    className: "text-red-700 bg-red-50",
  },
  "not-present": {
    label: "Not Present",
    className: "text-amber-700 bg-amber-50",
  },
  unclear: {
    label: "Unclear",
    className: "text-gray-600 bg-gray-50",
  },
};

function DisclaimerBanner() {
  return (
    <div className="flex items-start gap-2 rounded-xl bg-amber-50 border border-amber-200 px-3 py-2.5 text-caption text-amber-800">
      <AlertTriangle
        className="h-4 w-4 mt-0.5 shrink-0 text-amber-500"
        aria-hidden="true"
      />
      <span>{_DISCLAIMER}</span>
    </div>
  );
}

function SeverityChip({
  severity,
  count,
}: {
  severity: keyof typeof SEVERITY_CONFIG;
  count: number;
}) {
  if (count === 0) return null;
  const cfg = SEVERITY_CONFIG[severity];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-lg px-2 py-0.5 text-caption font-semibold",
        cfg.bgClass,
        cfg.textClass,
      )}
    >
      <span
        className={cn("inline-block h-1.5 w-1.5 rounded-full", cfg.dotClass)}
      />
      {count} {cfg.label}
    </span>
  );
}

function RiskFlagCard({ flag }: { flag: ContractRiskFlag }) {
  const [open, setOpen] = React.useState(false);
  const cfg =
    SEVERITY_CONFIG[flag.severity as keyof typeof SEVERITY_CONFIG] ??
    SEVERITY_CONFIG.info;
  return (
    <div
      className={cn(
        "rounded-lg border overflow-hidden",
        cfg.borderClass,
        cfg.bgClass,
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-3 py-2.5 flex items-start gap-2 active:opacity-70 no-tap-highlight"
        aria-expanded={open}
      >
        <span
          className={cn(
            "inline-block h-2 w-2 rounded-full mt-1 shrink-0",
            cfg.dotClass,
          )}
        />
        <div className="flex-1">
          <p className={cn("text-caption font-semibold", cfg.textClass)}>
            {flag.title}
          </p>
          <p className="text-caption text-label-secondary mt-0.5">
            {flag.summary}
          </p>
        </div>
        <span className={cn("text-caption shrink-0 mt-0.5", cfg.textClass)}>
          {open ? "Less" : "More"}
        </span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 border-t border-current/10">
          <div>
            <p className="text-caption text-label-tertiary font-medium mt-2 mb-0.5">
              Verbatim ({flag.location})
            </p>
            <blockquote className="border-l-2 border-current/30 pl-3 text-caption italic text-label-secondary leading-relaxed">
              "{flag.verbatim}"
            </blockquote>
          </div>
          <div>
            <p className="text-caption text-label-tertiary font-medium mb-0.5">
              Why it matters
            </p>
            <p className="text-caption text-label-secondary leading-relaxed">
              {flag.why_it_matters}
            </p>
          </div>
          <div>
            <p className="text-caption text-label-tertiary font-medium mb-0.5">
              Suggested action
            </p>
            <p className={cn("text-caption font-medium", cfg.textClass)}>
              {flag.suggested_action}
            </p>
          </div>
          {flag.suggested_redline && (
            <div>
              <p className="text-caption text-label-tertiary font-medium mb-0.5">
                Suggested redline
              </p>
              <p className="text-caption text-label-secondary italic leading-relaxed bg-white/60 rounded px-2 py-1">
                {flag.suggested_redline}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MissingProtectionCard({
  protection,
}: {
  protection: ContractMissingProtection;
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-3 py-2.5 flex items-start gap-2 active:opacity-70 no-tap-highlight"
        aria-expanded={open}
      >
        <span className="inline-block h-2 w-2 rounded-full mt-1 shrink-0 bg-amber-400" />
        <div className="flex-1">
          <p className="text-caption font-semibold text-amber-700">
            {protection.title}
          </p>
          <p className="text-caption text-label-secondary mt-0.5 text-xs">
            {protection.category}
          </p>
        </div>
        <span className="text-caption shrink-0 mt-0.5 text-amber-700">
          {open ? "Less" : "More"}
        </span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 border-t border-amber-200">
          <div className="mt-2">
            <p className="text-caption text-label-tertiary font-medium mb-0.5">
              Why it's typical
            </p>
            <p className="text-caption text-label-secondary leading-relaxed">
              {protection.why_typical}
            </p>
          </div>
          <div>
            <p className="text-caption text-label-tertiary font-medium mb-0.5">
              Suggested clause
            </p>
            <p className="text-caption text-label-secondary italic leading-relaxed bg-white/60 rounded px-2 py-1">
              {protection.suggested_clause}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function MarketTermsRow({
  label,
  entry,
}: {
  label: string;
  entry: MarketTermsEntry;
}) {
  const [open, setOpen] = React.useState(false);
  const vcfg = VERDICT_CONFIG[entry.verdict] ?? VERDICT_CONFIG["unclear"];
  return (
    <div className="border-b border-separator last:border-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between py-2.5 px-1 active:opacity-70 no-tap-highlight"
        aria-expanded={open}
      >
        <span className="text-caption text-label-primary">{label}</span>
        <span
          className={cn(
            "text-caption font-medium rounded px-1.5 py-0.5",
            vcfg.className,
          )}
        >
          {vcfg.label}
        </span>
      </button>
      {open && entry.notes && (
        <p className="px-1 pb-2.5 text-caption text-label-secondary leading-relaxed">
          {entry.notes}
        </p>
      )}
    </div>
  );
}

const MARKET_TERM_LABELS: Record<string, string> = {
  payment_terms: "Payment Terms",
  retention: "Retention",
  indemnification: "Indemnification",
  limitation_of_liability: "Limitation of Liability",
  termination: "Termination",
  change_orders: "Change Orders",
  dispute_resolution: "Dispute Resolution",
  insurance: "Insurance",
};

export function ContractReviewView({
  artifact,
  mode = "view",
}: {
  artifact: ContractReviewMetadata;
  mode?: "view" | "print";
}) {
  const isPrint = mode === "print";

  const riskFlags = Array.isArray(artifact.risk_flags) ? artifact.risk_flags : [];
  const missing = Array.isArray(artifact.missing_protections)
    ? artifact.missing_protections
    : [];
  const marketTerms = artifact.market_terms_assessment ?? {};
  const actions = Array.isArray(artifact.recommended_actions)
    ? artifact.recommended_actions
    : [];
  const citations = Array.isArray(artifact.citations) ? artifact.citations : [];

  // Severity counts
  const counts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
  for (const f of riskFlags) {
    const s = f.severity as keyof typeof counts;
    if (s in counts) counts[s]++;
  }

  // Group flags by severity order
  const severityOrder: Array<keyof typeof counts> = [
    "critical",
    "high",
    "medium",
    "low",
    "info",
  ];

  return (
    <div className="space-y-3">
      {/* ── Disclaimer (non-dismissable) ── */}
      <DisclaimerBanner />

      {/* ── Hero ── */}
      <ArtifactCard>
        <ArtifactCardHeader>
          <div className="flex flex-wrap gap-1.5 mb-3">
            {severityOrder.map((s) => (
              <SeverityChip key={s} severity={s} count={counts[s]} />
            ))}
          </div>
          {artifact.plain_english_summary && (
            <p className="text-footnote text-label-secondary leading-relaxed">
              {artifact.plain_english_summary}
            </p>
          )}
        </ArtifactCardHeader>
      </ArtifactCard>

      {/* ── Risk Flags ── */}
      {riskFlags.length > 0 && (
        <Section
          title={`Risk Flags (${riskFlags.length})`}
          defaultOpen
          printForceOpen={isPrint}
        >
          <div className="space-y-2">
            {severityOrder.flatMap((sev) =>
              riskFlags
                .filter((f) => f.severity === sev)
                .map((flag, i) => (
                  <RiskFlagCard key={`${sev}-${i}`} flag={flag} />
                ))
            )}
          </div>
        </Section>
      )}

      {/* ── Missing Protections ── */}
      {missing.length > 0 && (
        <Section
          title={`Missing Protections (${missing.length})`}
          defaultOpen={false}
          printForceOpen={isPrint}
        >
          <div className="space-y-2">
            {missing.map((p, i) => (
              <MissingProtectionCard key={i} protection={p} />
            ))}
          </div>
        </Section>
      )}

      {/* ── Market Terms ── */}
      {Object.keys(marketTerms).length > 0 && (
        <Section
          title="Market Terms Assessment"
          defaultOpen={false}
          printForceOpen={isPrint}
        >
          <p className="text-caption text-label-tertiary mb-2">
            Ohio commercial construction context. Tap a row for details.
          </p>
          <div>
            {Object.entries(marketTerms).map(([key, entry]) => (
              <MarketTermsRow
                key={key}
                label={MARKET_TERM_LABELS[key] ?? key}
                entry={entry as MarketTermsEntry}
              />
            ))}
          </div>
        </Section>
      )}

      {/* ── Recommended Actions ── */}
      {actions.length > 0 && (
        <Section
          title="Recommended Actions"
          defaultOpen
          printForceOpen={isPrint}
        >
          <ol className="space-y-2">
            {actions.map((action, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="text-caption font-bold text-accent shrink-0 mt-0.5">
                  {i + 1}.
                </span>
                <span className="text-caption text-label-primary leading-relaxed">
                  {action}
                </span>
              </li>
            ))}
          </ol>
        </Section>
      )}

      {/* ── Citations ── */}
      {citations.length > 0 && (
        <Section
          title="Citations"
          defaultOpen={false}
          printForceOpen={isPrint}
        >
          <div className="space-y-2">
            {citations.map((c: any, i: number) => (
              <div key={i} className="flex items-start gap-2">
                <span className="text-caption text-label-tertiary shrink-0 font-medium">
                  {c.location}
                </span>
                <span className="text-caption text-label-secondary italic">
                  "{c.quote}"
                </span>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}
