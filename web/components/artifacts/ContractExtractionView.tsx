"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { AlertTriangle } from "lucide-react";
import type { ContractExtractionMetadata } from "@/lib/schemas";
import {
  ArtifactCard,
  ArtifactCardBody,
  ArtifactCardHeader,
} from "./shared/ArtifactCard";
import { Section } from "./shared/Section";
import { StatPill } from "./shared/StatPill";

const _DISCLAIMER =
  "AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision.";

function formatUSD(v: number | null | undefined): string {
  if (v == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(v);
}

function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return d;
  }
}

function ContractTypeChip({ type }: { type: string | null | undefined }) {
  if (!type) return null;
  const label = type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return (
    <span className="inline-flex items-center rounded-lg bg-accent/15 px-2 py-0.5 text-caption text-accent font-medium">
      {label}
    </span>
  );
}

function DisclaimerBanner({ text }: { text?: string }) {
  return (
    <div className="flex items-start gap-2 rounded-xl bg-amber-50 border border-amber-200 px-3 py-2.5 text-caption text-amber-800">
      <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0 text-amber-500" aria-hidden="true" />
      <span>{text ?? _DISCLAIMER}</span>
    </div>
  );
}

function KeyValueRow({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-2 py-2 border-b border-separator last:border-0">
      <span className="text-caption text-label-secondary shrink-0">{label}</span>
      <span className="text-caption text-label-primary text-right">{value}</span>
    </div>
  );
}

export function ContractExtractionView({
  artifact,
  mode = "view",
}: {
  artifact: ContractExtractionMetadata;
  mode?: "view" | "print";
}) {
  const isPrint = mode === "print";
  const disclaimer = typeof artifact.disclaimer === "string" ? artifact.disclaimer : _DISCLAIMER;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const a = artifact as any;
  const parties: any[] = Array.isArray(a.parties) ? a.parties : [];
  const dates: any[] = Array.isArray(a.key_dates) ? a.key_dates : (Array.isArray(a.key_milestones) ? a.key_milestones : []);
  const clauses: any[] = Array.isArray(a.notable_clauses) ? a.notable_clauses : (Array.isArray(a.notable_clauses) ? [] : []);
  const paymentTermsSummary: string = a.payment_terms_summary || a.payment_terms || "";
  const totalValue: number | null = a.total_value_usd ?? null;

  return (
    <div className="space-y-3">
      {/* ── Disclaimer ── */}
      <DisclaimerBanner text={disclaimer} />

      {/* ── Hero ── */}
      <ArtifactCard>
        <ArtifactCardHeader>
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <ContractTypeChip type={artifact.contract_type} />
            {totalValue != null && (
              <StatPill label="Value" value={formatUSD(totalValue)} />
            )}
          </div>
          {a.plain_english_summary && (
            <p className="text-footnote text-label-secondary mt-1 leading-relaxed">
              {String(a.plain_english_summary)}
            </p>
          )}
        </ArtifactCardHeader>
      </ArtifactCard>

      {/* ── Parties ── */}
      {parties.length > 0 && (
        <Section title="Parties" defaultOpen printForceOpen={isPrint}>
          <div className="space-y-0">
            {parties.map((p, i) => (
              <KeyValueRow
                key={i}
                label={String(p.role ?? `Party ${i + 1}`)}
                value={
                  <>
                    <span className="block font-medium">{String(p.name ?? "—")}</span>
                    {p.address && (
                      <span className="block text-label-tertiary text-caption">
                        {String(p.address)}
                      </span>
                    )}
                  </>
                }
              />
            ))}
          </div>
        </Section>
      )}

      {/* ── Key Dates ── */}
      {(dates.length > 0 || a.effective_date || a.expiration_date) && (
        <Section title="Key Dates" defaultOpen printForceOpen={isPrint}>
          <div className="space-y-0">
            {a.effective_date && (
              <KeyValueRow
                label="Effective Date"
                value={formatDate(a.effective_date as string)}
              />
            )}
            {a.expiration_date && (
              <KeyValueRow
                label="Expiration Date"
                value={formatDate(a.expiration_date as string)}
              />
            )}
            {(dates as Array<Record<string, unknown>>).map((d, i) => (
              <KeyValueRow
                key={i}
                label={String(d["label"] ?? d["date_type"] ?? "Date")}
                value={formatDate(d["date"] as string | undefined)}
              />
            ))}
          </div>
        </Section>
      )}

      {/* ── Money ── */}
      {(totalValue != null || paymentTermsSummary) && (
        <Section title="Money" defaultOpen={false} printForceOpen={isPrint}>
          <div className="space-y-0">
            {totalValue != null && (
              <KeyValueRow
                label="Total Contract Value"
                value={formatUSD(totalValue)}
              />
            )}
            {paymentTermsSummary && (
              <div className="pt-2">
                <p className="text-caption text-label-secondary leading-relaxed">
                  {paymentTermsSummary}
                </p>
              </div>
            )}
          </div>
        </Section>
      )}

      {/* ── Obligations ── */}
      {a.obligations &&
        Object.keys(a.obligations as Record<string, unknown>).length > 0 && (
          <Section title="Obligations" defaultOpen={false} printForceOpen={isPrint}>
            <div className="space-y-2">
              {Object.entries(
                (a.obligations ?? {}) as Record<string, string[]>
              ).map(([party, items]) => (
                <div key={party}>
                  <p className="text-caption font-semibold text-label-primary mb-1">
                    {party}
                  </p>
                  <ul className="space-y-1 pl-3">
                    {(items as string[]).map((item, i) => (
                      <li
                        key={i}
                        className="text-caption text-label-secondary flex gap-1"
                      >
                        <span className="text-label-tertiary">•</span>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </Section>
        )}

      {/* ── Notable Clauses ── */}
      {clauses.length > 0 && (
        <Section title="Notable Clauses" defaultOpen={false} printForceOpen={isPrint}>
          <div className="space-y-3">
            {clauses.map((clause: any, i: number) => (
              <ClauseAccordion key={i} clause={clause} />
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

function ClauseAccordion({ clause }: { clause: any }) {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="rounded-lg bg-bg-tertiary overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-start justify-between gap-2 px-3 py-2 text-left active:bg-bg-elevated no-tap-highlight"
        aria-expanded={open}
      >
        <div className="flex-1">
          <span className="text-caption font-medium text-label-primary block">
            {clause.heading ?? clause.section ?? "Clause"}
          </span>
          {clause.section && clause.heading && (
            <span className="text-caption text-label-tertiary">{clause.section}</span>
          )}
          {!open && clause.paraphrase && (
            <p className="text-caption text-label-secondary mt-0.5 line-clamp-2">
              {clause.paraphrase}
            </p>
          )}
        </div>
        <span className="text-caption text-accent shrink-0 mt-0.5">
          {open ? "Less" : "More"}
        </span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2">
          {clause.paraphrase && (
            <p className="text-caption text-label-secondary leading-relaxed">
              {clause.paraphrase}
            </p>
          )}
          {clause.verbatim && (
            <blockquote className="border-l-2 border-separator pl-3 text-caption text-label-tertiary italic leading-relaxed">
              "{clause.verbatim}"
            </blockquote>
          )}
        </div>
      )}
    </div>
  );
}
