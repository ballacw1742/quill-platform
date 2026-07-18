"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ChevronRight, Plus, Trash2 } from "lucide-react";
import {
  BottomSheet,
  BottomSheetActionBar,
  BottomSheetBody,
  BottomSheetTopBar,
} from "@/components/ui/sheet";
import { DraftAttorneyBanner } from "@/components/contracts/DraftAttorneyBanner";
import { useContractTemplates, useCreateContractDraft } from "@/lib/api";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

// ── Step types ─────────────────────────────────────────────────────────────
type Step = "mode" | "type" | "parties" | "terms" | "scope" | "review";

const CONTRACT_TYPE_OPTIONS = [
  { value: "owner_gc", label: "Owner ↔ GC" },
  { value: "subcontract", label: "Subcontract" },
  { value: "change_order", label: "Change Order" },
  { value: "purchase_order", label: "Purchase Order" },
  { value: "letter_of_intent", label: "Letter of Intent" },
  { value: "nda", label: "NDA" },
  { value: "msa", label: "Master Service Agreement" },
  { value: "equipment_lease", label: "Equipment Lease" },
  { value: "lien_waiver", label: "Lien Waiver" },
  { value: "other", label: "Other" },
] as const;

// ── Grouped template picker ────────────────────────────────────────────────
type TemplateOption = {
  template_id: string;
  contract_type: string;
  display_name: string;
};

function TemplatePicker({
  templates,
  selectedId,
  onSelect,
}: {
  templates: TemplateOption[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  // Group by contract_type
  const grouped = React.useMemo(() => {
    const map = new Map<string, TemplateOption[]>();
    for (const t of templates) {
      const ct = t.contract_type;
      if (!map.has(ct)) map.set(ct, []);
      map.get(ct)!.push(t);
    }
    return map;
  }, [templates]);

  return (
    <div className="space-y-4">
      {Array.from(grouped.entries()).map(([ct, items]) => (
        <div key={ct}>
          <p className="text-caption font-semibold text-label-tertiary uppercase tracking-wide mb-1.5">
            {ct.replace(/_/g, " ")}
          </p>
          <div className="space-y-1">
            {items.map((t) => (
              <button
                key={t.template_id}
                type="button"
                onClick={() => onSelect(t.template_id)}
                className={cn(
                  "w-full text-left flex items-center justify-between px-3 py-2.5 rounded-xl border transition-colors no-tap-highlight",
                  selectedId === t.template_id
                    ? "border-accent bg-accent/5 text-accent"
                    : "border-separator bg-bg-elevated text-label-primary active:bg-bg-tertiary",
                )}
              >
                <span className="text-callout">{t.display_name}</span>
                {selectedId === t.template_id && (
                  <span className="text-caption font-semibold text-accent">✓</span>
                )}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Party row ──────────────────────────────────────────────────────────────
type Party = {
  role: string;
  name: string;
  address: string;
  contact: string;
};

function PartyRow({
  party,
  index,
  onChange,
  onRemove,
  canRemove,
}: {
  party: Party;
  index: number;
  onChange: (p: Party) => void;
  onRemove: () => void;
  canRemove: boolean;
}) {
  const [expanded, setExpanded] = React.useState(index < 2);

  return (
    <div className="rounded-2xl border border-hairline bg-bg-elevated overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2.5 no-tap-highlight active:bg-bg-tertiary"
      >
        <div className="text-left">
          <p className="text-callout font-medium text-label-primary">
            {party.name || `Party ${index + 1}`}
          </p>
          <p className="text-caption text-label-tertiary">
            {party.role || "Role not set"}
          </p>
        </div>
        <ChevronRight
          className={cn(
            "h-4 w-4 text-label-tertiary transition-transform",
            expanded && "rotate-90",
          )}
        />
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2 border-t border-separator">
          <div className="mt-2">
            <label className="text-caption text-label-tertiary mb-0.5 block">
              Role *
            </label>
            <input
              type="text"
              value={party.role}
              onChange={(e) => onChange({ ...party, role: e.target.value })}
              placeholder="e.g. Contractor, Owner, Subcontractor"
              className="w-full rounded-lg border border-separator bg-bg-primary px-3 py-2 text-callout text-label-primary focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <div>
            <label className="text-caption text-label-tertiary mb-0.5 block">
              Name *
            </label>
            <input
              type="text"
              value={party.name}
              onChange={(e) => onChange({ ...party, name: e.target.value })}
              placeholder="Company or individual name"
              className="w-full rounded-lg border border-separator bg-bg-primary px-3 py-2 text-callout text-label-primary focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <div>
            <label className="text-caption text-label-tertiary mb-0.5 block">
              Address
            </label>
            <input
              type="text"
              value={party.address}
              onChange={(e) => onChange({ ...party, address: e.target.value })}
              placeholder="Street address, City, State ZIP"
              className="w-full rounded-lg border border-separator bg-bg-primary px-3 py-2 text-callout text-label-primary focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <div>
            <label className="text-caption text-label-tertiary mb-0.5 block">
              Contact
            </label>
            <input
              type="text"
              value={party.contact}
              onChange={(e) => onChange({ ...party, contact: e.target.value })}
              placeholder="Email or phone"
              className="w-full rounded-lg border border-separator bg-bg-primary px-3 py-2 text-callout text-label-primary focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          {canRemove && (
            <button
              type="button"
              onClick={onRemove}
              className="flex items-center gap-1 text-caption text-danger active:opacity-70 no-tap-highlight mt-1"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Remove party
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Key term row ───────────────────────────────────────────────────────────
type KeyTerm = { topic: string; requirement: string };

function KeyTermRow({
  term,
  index,
  onChange,
  onRemove,
}: {
  term: KeyTerm;
  index: number;
  onChange: (t: KeyTerm) => void;
  onRemove: () => void;
}) {
  return (
    <div className="flex items-start gap-2 rounded-2xl border border-hairline bg-bg-elevated px-3 py-2.5">
      <div className="flex-1 space-y-1.5">
        <input
          type="text"
          value={term.topic}
          onChange={(e) => onChange({ ...term, topic: e.target.value })}
          placeholder={`Topic ${index + 1} (e.g. indemnification)`}
          className="w-full rounded-lg border border-separator bg-bg-primary px-2.5 py-1.5 text-caption text-label-primary focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <input
          type="text"
          value={term.requirement}
          onChange={(e) => onChange({ ...term, requirement: e.target.value })}
          placeholder="Requirement (e.g. mutual indemnification only)"
          className="w-full rounded-lg border border-separator bg-bg-primary px-2.5 py-1.5 text-caption text-label-primary focus:outline-none focus:ring-1 focus:ring-accent"
        />
      </div>
      <button
        type="button"
        onClick={onRemove}
        className="p-1.5 rounded-lg active:bg-bg-tertiary no-tap-highlight text-label-tertiary"
        aria-label={`Remove term ${index + 1}`}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────
export type DraftContractSheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function DraftContractSheet({ open, onOpenChange }: DraftContractSheetProps) {
  const router = useRouter();
  const [step, setStep] = React.useState<Step>("mode");

  // Form state
  const [mode, setMode] = React.useState<"template" | "negotiated">("template");
  const [contractType, setContractType] = React.useState("");
  const [templateId, setTemplateId] = React.useState<string | null>(null);
  const [parties, setParties] = React.useState<Party[]>([
    { role: "Contractor", name: "", address: "", contact: "" },
    { role: "Subcontractor", name: "", address: "", contact: "" },
  ]);
  const [effectiveDate, setEffectiveDate] = React.useState("");
  const [expirationDate, setExpirationDate] = React.useState("");
  const [totalValue, setTotalValue] = React.useState("");
  const [paymentTerms, setPaymentTerms] = React.useState("");
  const [keyTerms, setKeyTerms] = React.useState<KeyTerm[]>([]);
  const [scopeSummary, setScopeSummary] = React.useState("");
  const [notes, setNotes] = React.useState("");

  const { data: templatesData } = useContractTemplates();
  const templates = templatesData?.items ?? [];

  const createDraft = useCreateContractDraft();

  // Reset form when sheet closes — pin useEffect dep to [open] only
  // to avoid infinite-loop with mutation object per LESSONS.md lesson 7.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  React.useEffect(() => {
    if (!open) {
      setStep("mode");
      setMode("template");
      setContractType("");
      setTemplateId(null);
      setParties([
        { role: "Contractor", name: "", address: "", contact: "" },
        { role: "Subcontractor", name: "", address: "", contact: "" },
      ]);
      setEffectiveDate("");
      setExpirationDate("");
      setTotalValue("");
      setPaymentTerms("");
      setKeyTerms([]);
      setScopeSummary("");
      setNotes("");
      createDraft.reset();
    }
  }, [open]);

  const stepTitles: Record<Step, string> = {
    mode: "Draft Contract",
    type: mode === "template" ? "Choose Template" : "Contract Type",
    parties: "Parties",
    terms: "Key Terms",
    scope: "Scope & Notes",
    review: "Review Request",
  };

  const stepOrder: Step[] = ["mode", "type", "parties", "terms", "scope", "review"];
  const currentIdx = stepOrder.indexOf(step);

  const handleBack = () => {
    if (currentIdx > 0) setStep(stepOrder[currentIdx - 1]);
    else onOpenChange(false);
  };

  const handleNext = () => {
    if (currentIdx < stepOrder.length - 1)
      setStep(stepOrder[currentIdx + 1]);
  };

  const canProceed = () => {
    if (step === "mode") return true;
    if (step === "type") {
      if (mode === "template") return !!templateId;
      return !!contractType;
    }
    if (step === "parties") return parties.length >= 2 && parties.every((p) => p.role && p.name);
    return true;
  };

  const handleConfirm = async () => {
    try {
      const result: any = await createDraft.mutateAsync({
        mode,
        contract_type: contractType || (templates.find((t) => t.template_id === templateId)?.contract_type ?? "other"),
        template_id: mode === "template" ? templateId : null,
        parties: parties.map((p) => ({
          role: p.role,
          name: p.name,
          address: p.address || undefined,
          contact: p.contact || undefined,
        })),
        effective_date: effectiveDate || null,
        expiration_date: expirationDate || null,
        total_value_usd: totalValue ? parseFloat(totalValue) : null,
        payment_terms: paymentTerms || null,
        scope_summary: scopeSummary,
        key_terms_requested: keyTerms.filter((kt) => kt.topic && kt.requirement),
        jurisdiction: "Ohio",
        notes,
        prior_contract_upload_id: null,
      });
      toast.success("Draft request created. Axe is drafting your contract…");
      onOpenChange(false);
      if (result?.upload_id) {
        router.push(`/contracts/${result.upload_id}`);
      }
    } catch (err: any) {
      toast.error(err?.message ?? "Failed to create draft request.");
    }
  };

  return (
    <BottomSheet open={open} onOpenChange={onOpenChange}>
      <BottomSheetTopBar
        title={stepTitles[step]}
        onClose={() => onOpenChange(false)}
      />

      <BottomSheetBody>
        {/* Step 1: Mode */}
        {step === "mode" && (
          <div className="space-y-3">
            <p className="text-callout text-label-secondary">
              How would you like to draft this contract?
            </p>
            <div className="space-y-2">
              {(["template", "negotiated"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={cn(
                    "w-full text-left rounded-xl border px-4 py-3 transition-colors no-tap-highlight",
                    mode === m
                      ? "border-accent bg-accent/5"
                      : "border-separator bg-bg-elevated active:bg-bg-tertiary",
                  )}
                >
                  <p className={cn("text-callout font-semibold", mode === m ? "text-accent" : "text-label-primary")}>
                    {m === "template" ? "From Template" : "Negotiated (Free-form)"}
                  </p>
                  <p className="text-caption text-label-secondary mt-0.5">
                    {m === "template"
                      ? "Start from a pre-built contract template for your contract type."
                      : "Describe the deal in plain terms; Axe drafts from scratch."}
                  </p>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Step 2: Template picker or contract type selector */}
        {step === "type" && mode === "template" && (
          <div className="space-y-3">
            <p className="text-callout text-label-secondary">
              Choose a template to start from.
            </p>
            {templates.length === 0 ? (
              <div className="py-4 text-center text-caption text-label-secondary">
                Loading templates…
              </div>
            ) : (
              <TemplatePicker
                templates={templates}
                selectedId={templateId}
                onSelect={(id) => {
                  setTemplateId(id);
                  const tmpl = templates.find((t) => t.template_id === id);
                  if (tmpl) setContractType(tmpl.contract_type);
                }}
              />
            )}
          </div>
        )}

        {step === "type" && mode === "negotiated" && (
          <div className="space-y-3">
            <p className="text-callout text-label-secondary">
              Select the contract type.
            </p>
            <div className="space-y-1">
              {CONTRACT_TYPE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setContractType(opt.value)}
                  className={cn(
                    "w-full text-left rounded-xl border px-3 py-2.5 no-tap-highlight",
                    contractType === opt.value
                      ? "border-accent bg-accent/5 text-accent"
                      : "border-separator bg-bg-elevated text-label-primary active:bg-bg-tertiary",
                  )}
                >
                  <span className="text-callout">{opt.label}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Step 3: Parties */}
        {step === "parties" && (
          <div className="space-y-3">
            <p className="text-callout text-label-secondary">
              Add at least 2 parties. Expand each to fill in address and contact.
            </p>
            <div className="space-y-2">
              {parties.map((party, i) => (
                <PartyRow
                  key={i}
                  party={party}
                  index={i}
                  onChange={(p) => {
                    const next = [...parties];
                    next[i] = p;
                    setParties(next);
                  }}
                  onRemove={() => setParties(parties.filter((_, j) => j !== i))}
                  canRemove={parties.length > 2}
                />
              ))}
            </div>
            <button
              type="button"
              onClick={() =>
                setParties([...parties, { role: "", name: "", address: "", contact: "" }])
              }
              className="flex items-center gap-1.5 text-callout text-accent active:opacity-70 no-tap-highlight py-1"
            >
              <Plus className="h-4 w-4" />
              Add party
            </button>
          </div>
        )}

        {/* Step 4: Key terms */}
        {step === "terms" && (
          <div className="space-y-3">
            <p className="text-callout text-label-secondary">
              Set dates, value, payment terms, and specific clause requirements.
            </p>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-caption text-label-tertiary mb-0.5 block">
                  Effective Date
                </label>
                <input
                  type="date"
                  value={effectiveDate}
                  onChange={(e) => setEffectiveDate(e.target.value)}
                  className="w-full rounded-lg border border-separator bg-bg-primary px-3 py-2 text-callout text-label-primary focus:outline-none focus:ring-1 focus:ring-accent"
                />
              </div>
              <div>
                <label className="text-caption text-label-tertiary mb-0.5 block">
                  Expiration Date
                </label>
                <input
                  type="date"
                  value={expirationDate}
                  onChange={(e) => setExpirationDate(e.target.value)}
                  className="w-full rounded-lg border border-separator bg-bg-primary px-3 py-2 text-callout text-label-primary focus:outline-none focus:ring-1 focus:ring-accent"
                />
              </div>
            </div>
            <div>
              <label className="text-caption text-label-tertiary mb-0.5 block">
                Total Value (USD)
              </label>
              <input
                type="number"
                value={totalValue}
                onChange={(e) => setTotalValue(e.target.value)}
                placeholder="e.g. 125000"
                min={0}
                className="w-full rounded-lg border border-separator bg-bg-primary px-3 py-2 text-callout text-label-primary focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>
            <div>
              <label className="text-caption text-label-tertiary mb-0.5 block">
                Payment Terms
              </label>
              <input
                type="text"
                value={paymentTerms}
                onChange={(e) => setPaymentTerms(e.target.value)}
                placeholder="e.g. Net 30, Pay-when-paid"
                className="w-full rounded-lg border border-separator bg-bg-primary px-3 py-2 text-callout text-label-primary focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>

            <div className="space-y-2">
              <label className="text-caption text-label-tertiary block">
                Specific Clause Requirements
              </label>
              {keyTerms.map((kt, i) => (
                <KeyTermRow
                  key={i}
                  term={kt}
                  index={i}
                  onChange={(t) => {
                    const next = [...keyTerms];
                    next[i] = t;
                    setKeyTerms(next);
                  }}
                  onRemove={() => setKeyTerms(keyTerms.filter((_, j) => j !== i))}
                />
              ))}
              <button
                type="button"
                onClick={() => setKeyTerms([...keyTerms, { topic: "", requirement: "" }])}
                className="flex items-center gap-1.5 text-callout text-accent active:opacity-70 no-tap-highlight py-1"
              >
                <Plus className="h-4 w-4" />
                Add clause requirement
              </button>
            </div>
          </div>
        )}

        {/* Step 5: Scope + notes */}
        {step === "scope" && (
          <div className="space-y-3">
            <p className="text-callout text-label-secondary">
              Describe the scope of work and any special instructions.
            </p>
            <div>
              <label className="text-caption text-label-tertiary mb-0.5 block">
                Scope Summary *
              </label>
              <textarea
                value={scopeSummary}
                onChange={(e) => setScopeSummary(e.target.value)}
                placeholder="Describe what this contract covers — work to be performed, deliverables, etc."
                rows={4}
                className="w-full rounded-xl border border-separator bg-bg-primary px-3 py-2.5 text-callout text-label-primary focus:outline-none focus:ring-1 focus:ring-accent resize-none"
              />
            </div>
            <div>
              <label className="text-caption text-label-tertiary mb-0.5 block">
                Notes / Special Instructions
              </label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Any special instructions, context, or preferences for Axe…"
                rows={3}
                className="w-full rounded-xl border border-separator bg-bg-primary px-3 py-2.5 text-callout text-label-primary focus:outline-none focus:ring-1 focus:ring-accent resize-none"
              />
            </div>
          </div>
        )}

        {/* Step 6: Review */}
        {step === "review" && (
          <div className="space-y-4">
            <DraftAttorneyBanner />
            <div className="rounded-2xl border border-hairline bg-bg-elevated divide-y divide-separator">
              <div className="flex justify-between items-center px-3 py-2.5">
                <span className="text-caption text-label-tertiary">Mode</span>
                <span className="text-callout font-medium text-label-primary capitalize">
                  {mode}
                </span>
              </div>
              {templateId && (
                <div className="flex justify-between items-center px-3 py-2.5">
                  <span className="text-caption text-label-tertiary">Template</span>
                  <span className="text-callout text-label-primary">{templateId}</span>
                </div>
              )}
              <div className="flex justify-between items-center px-3 py-2.5">
                <span className="text-caption text-label-tertiary">Contract Type</span>
                <span className="text-callout text-label-primary">
                  {contractType.replace(/_/g, " ")}
                </span>
              </div>
              <div className="flex justify-between items-center px-3 py-2.5">
                <span className="text-caption text-label-tertiary">Parties</span>
                <span className="text-callout text-label-primary">{parties.length}</span>
              </div>
              {scopeSummary && (
                <div className="px-3 py-2.5">
                  <p className="text-caption text-label-tertiary mb-0.5">Scope</p>
                  <p className="text-caption text-label-secondary line-clamp-3">{scopeSummary}</p>
                </div>
              )}
            </div>
            {createDraft.isError && (
              <div className="text-caption text-danger rounded-lg bg-danger/10 border border-danger/20 px-3 py-2">
                {(createDraft.error as Error)?.message ?? "Failed to create draft request."}
              </div>
            )}
          </div>
        )}
      </BottomSheetBody>

      <BottomSheetActionBar>
        {step !== "mode" && (
          <button
            type="button"
            onClick={handleBack}
            className="rounded-xl border border-hairline bg-bg-elevated px-4 py-3 min-h-[44px] text-callout font-medium text-label-primary active:bg-bg-tertiary no-tap-highlight"
          >
            Back
          </button>
        )}
        {step !== "review" ? (
          <button
            type="button"
            onClick={handleNext}
            disabled={!canProceed()}
            className={cn(
              "flex-1 rounded-xl px-4 py-3 min-h-[44px] text-callout font-semibold transition-colors no-tap-highlight",
              canProceed()
                ? "bg-accent text-white active:bg-accent/80"
                : "bg-bg-elevated text-label-tertiary",
            )}
          >
            Next
          </button>
        ) : (
          <button
            type="button"
            onClick={handleConfirm}
            disabled={createDraft.isPending}
            className={cn(
              "flex-1 rounded-xl px-4 py-3 min-h-[44px] text-callout font-semibold transition-colors no-tap-highlight",
              createDraft.isPending
                ? "bg-bg-elevated text-label-tertiary"
                : "bg-accent text-white active:bg-accent/80",
            )}
          >
            {createDraft.isPending ? "Creating…" : "Request Draft"}
          </button>
        )}
      </BottomSheetActionBar>
    </BottomSheet>
  );
}

export default DraftContractSheet;
