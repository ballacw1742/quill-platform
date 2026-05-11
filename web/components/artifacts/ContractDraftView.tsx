"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { ChevronDown } from "lucide-react";
import type { ContractDraftMetadata } from "@/lib/schemas";
import {
  ArtifactCard,
  ArtifactCardBody,
  ArtifactCardHeader,
} from "./shared/ArtifactCard";
import { Section } from "./shared/Section";
import { MarkdownBlock } from "./shared/MarkdownBlock";

const _DISCLAIMER =
  "AI-generated analysis. This is not legal advice. Review with qualified counsel before relying on it for any binding decision.";

// ── Contract type display names ───────────────────────────────────────────
const CONTRACT_TYPE_LABELS: Record<string, string> = {
  owner_gc: "Owner–GC",
  subcontract: "Subcontract",
  change_order: "Change Order",
  purchase_order: "Purchase Order",
  letter_of_intent: "Letter of Intent",
  nda: "NDA",
  msa: "MSA",
  equipment_lease: "Equipment Lease",
  insurance_certificate: "Insurance Certificate",
  lien_waiver: "Lien Waiver",
  other: "Other",
  unknown: "Contract",
};

// ── Hero section ──────────────────────────────────────────────────────────
function DraftHero({ artifact }: { artifact: ContractDraftMetadata }) {
  const typeLabel =
    CONTRACT_TYPE_LABELS[artifact.contract_type] ?? artifact.contract_type;

  return (
    <div className="px-4 py-4 space-y-3">
      {/* Title + contract_type chip */}
      <div className="flex items-start gap-2 flex-wrap">
        <h1 className="text-title3 font-bold text-label-primary flex-1 min-w-0">
          {artifact.title}
        </h1>
        <span className="shrink-0 inline-flex items-center rounded-full bg-blue-100 px-2.5 py-0.5 text-caption font-semibold text-blue-700">
          {typeLabel}
        </span>
      </div>

      {/* Summary */}
      {artifact.summary && (
        <p className="text-callout text-label-secondary leading-relaxed">
          {artifact.summary}
        </p>
      )}

      {/* Parties row */}
      {artifact.parties && artifact.parties.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {artifact.parties.map((party, i) => (
            <div
              key={i}
              className="rounded-lg bg-bg-elevated px-3 py-1.5 border border-separator"
            >
              <p className="text-caption text-label-tertiary capitalize">
                {party.role}
              </p>
              <p className="text-callout font-medium text-label-primary">
                {party.name}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Meta row: dates + value */}
      <div className="flex flex-wrap gap-3 text-caption text-label-secondary">
        {artifact.effective_date && (
          <span>
            <span className="font-medium text-label-primary">Effective:</span>{" "}
            {artifact.effective_date}
          </span>
        )}
        {artifact.expiration_date && (
          <span>
            <span className="font-medium text-label-primary">Expires:</span>{" "}
            {artifact.expiration_date}
          </span>
        )}
        {artifact.total_value_usd != null && (
          <span>
            <span className="font-medium text-label-primary">Value:</span>{" "}
            {new Intl.NumberFormat("en-US", {
              style: "currency",
              currency: "USD",
              maximumFractionDigits: 0,
            }).format(artifact.total_value_usd)}
          </span>
        )}
      </div>
    </div>
  );
}

// ── TOC ───────────────────────────────────────────────────────────────────
function DraftTOC({
  sections,
}: {
  sections: ContractDraftMetadata["sections"];
}) {
  if (!sections || sections.length === 0) return null;
  return (
    <Section title="Table of Contents" defaultOpen={false}>
      <ol className="list-none space-y-0.5 px-1 py-1">
        {sections.map((sec, i) => (
          <li key={i}>
            <a
              href={`#${sec.anchor}`}
              className="flex items-start gap-2 py-1.5 px-2 rounded-lg hover:bg-bg-elevated active:bg-bg-tertiary no-tap-highlight text-callout text-label-primary"
            >
              <span className="text-label-tertiary text-caption min-w-[1.5rem]">
                {i + 1}.
              </span>
              <div className="flex-1">
                <span className="font-medium">{sec.heading}</span>
                {sec.summary && (
                  <p className="text-caption text-label-secondary mt-0.5">
                    {sec.summary}
                  </p>
                )}
              </div>
            </a>
          </li>
        ))}
      </ol>
    </Section>
  );
}

// ── Attorney Review Focus ─────────────────────────────────────────────────
function AttorneyFocusCard({
  item,
}: {
  item: ContractDraftMetadata["attorney_review_focus"][number];
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="rounded-xl border border-amber-300 bg-amber-50 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-3 py-2.5 flex items-start gap-2 active:opacity-70 no-tap-highlight"
        aria-expanded={open}
      >
        <span className="inline-block h-2 w-2 rounded-full mt-1.5 shrink-0 bg-amber-500" />
        <div className="flex-1">
          <p className="text-callout font-semibold text-amber-800">
            {item.topic}
          </p>
          {!open && (
            <p className="text-caption text-label-secondary mt-0.5 line-clamp-1">
              {item.why}
            </p>
          )}
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-amber-600 mt-0.5 transition-transform shrink-0",
            open && "rotate-180",
          )}
          aria-hidden="true"
        />
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 border-t border-amber-200">
          <div className="mt-2">
            <p className="text-caption text-label-tertiary font-medium mb-0.5">
              Why counsel should review
            </p>
            <p className="text-caption text-label-secondary leading-relaxed">
              {item.why}
            </p>
          </div>
          <div>
            <p className="text-caption text-label-tertiary font-medium mb-0.5">
              Suggested question
            </p>
            <p className="text-caption font-medium text-amber-800 italic leading-relaxed bg-white/60 rounded px-2 py-1">
              {item.suggested_question}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Key Terms Addressed ───────────────────────────────────────────────────
function KeyTermsSection({
  keyTerms,
}: {
  keyTerms: ContractDraftMetadata["key_terms_addressed"];
}) {
  const entries = Object.entries(keyTerms ?? {});
  if (entries.length === 0) return null;
  return (
    <Section title="Key Terms Addressed">
      <div className="space-y-2 px-1 py-1">
        {entries.map(([topic, explanation]) => (
          <div
            key={topic}
            className="rounded-lg border border-separator bg-bg-primary px-3 py-2.5"
          >
            <p className="text-callout font-semibold text-label-primary capitalize">
              {topic.replace(/_/g, " ")}
            </p>
            <p className="text-caption text-label-secondary mt-0.5 leading-relaxed">
              {explanation}
            </p>
          </div>
        ))}
      </div>
    </Section>
  );
}

// ── Assumptions ───────────────────────────────────────────────────────────
function AssumptionsSection({
  assumptions,
}: {
  assumptions: ContractDraftMetadata["assumptions_made"];
}) {
  if (!assumptions || assumptions.length === 0) return null;
  return (
    <Section title="Assumptions Made">
      <ul className="list-none space-y-2 px-1 py-1">
        {assumptions.map((a, i) => (
          <li
            key={i}
            className="rounded-lg bg-bg-primary border border-separator px-3 py-2.5"
          >
            <p className="text-callout font-semibold text-label-primary capitalize">
              {a.topic.replace(/_/g, " ")}
            </p>
            <p className="text-caption text-label-secondary mt-0.5">
              <span className="font-medium">Assumed:</span> {a.assumption}
            </p>
            <p className="text-caption text-label-tertiary mt-0.5 italic">
              {a.why_made}
            </p>
          </li>
        ))}
      </ul>
    </Section>
  );
}

// ── Variables Used ────────────────────────────────────────────────────────
function VariablesSection({
  variables,
}: {
  variables: ContractDraftMetadata["variables_used"];
}) {
  const entries = Object.entries(variables ?? {});
  if (entries.length === 0) return null;
  return (
    <Section title="Variables Used" defaultOpen={false}>
      <div className="divide-y divide-separator px-1 py-1">
        {entries.map(([key, val]) => (
          <div key={key} className="flex justify-between gap-3 py-2 px-2">
            <span className="text-caption text-label-tertiary font-mono">
              {key}
            </span>
            <span className="text-caption text-label-primary text-right">
              {String(val ?? "")}
            </span>
          </div>
        ))}
      </div>
    </Section>
  );
}

// ── Main component ────────────────────────────────────────────────────────
export interface ContractDraftViewProps {
  artifact: ContractDraftMetadata;
  mode?: "view" | "print";
}

export function ContractDraftView({
  artifact,
  mode = "view",
}: ContractDraftViewProps) {
  const isPrint = mode === "print";

  return (
    <ArtifactCard>
      <ArtifactCardHeader>
        <DraftHero artifact={artifact} />
      </ArtifactCardHeader>

      <ArtifactCardBody>
        {/* TOC */}
        <DraftTOC sections={artifact.sections} />

        {/* Contract body */}
        <Section title="Contract Document" printForceOpen={isPrint}>
          <div className="px-2 py-2">
            <MarkdownBlock content={artifact.body_markdown} />
          </div>
        </Section>

        {/* Attorney Review Focus */}
        {artifact.attorney_review_focus &&
          artifact.attorney_review_focus.length > 0 && (
            <Section title="Attorney Review Focus" printForceOpen={isPrint}>
              <div className="space-y-2 px-1 py-1">
                {artifact.attorney_review_focus.map((item, i) => (
                  <AttorneyFocusCard key={i} item={item} />
                ))}
              </div>
            </Section>
          )}

        {/* Assumptions Made */}
        <AssumptionsSection assumptions={artifact.assumptions_made} />

        {/* Key Terms Addressed */}
        <KeyTermsSection keyTerms={artifact.key_terms_addressed} />

        {/* Variables Used (collapsed by default) */}
        <VariablesSection variables={artifact.variables_used} />

        {/* Canonical disclaimer footer */}
        <div className="px-4 py-3 mt-2">
          <p className="text-caption text-label-tertiary text-center leading-relaxed italic">
            {artifact.disclaimer ?? _DISCLAIMER}
          </p>
        </div>
      </ArtifactCardBody>
    </ArtifactCard>
  );
}

export default ContractDraftView;
