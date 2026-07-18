"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  Download,
  FileText,
  Loader2,
  PenLine,
  Send,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { MobileShell, TopBar, BackButton } from "@/components/layout/MobileShell";
import { ModuleAgentBar } from "@/components/journey/ModuleAgentBar";
import { ErrorBanner } from "@/components/ui/error-banner";
import { DraftAttorneyBanner } from "@/components/contracts/DraftAttorneyBanner";
import { RedraftSheet } from "@/components/contracts/RedraftSheet";
import { ContractExtractionView } from "@/components/artifacts/ContractExtractionView";
import { ContractReviewView } from "@/components/artifacts/ContractReviewView";
import { ContractInterpretationView } from "@/components/artifacts/ContractInterpretationView";
import { ContractDraftView } from "@/components/artifacts/ContractDraftView";
import {
  useContract,
  useContractReviews,
  useContractInterpretations,
  useDispatchContractReview,
  useInterpretContract,
  useContractDraft,
} from "@/lib/api";
import {
  ContractExtractionMetadataSchema,
  ContractDraftMetadataSchema,
} from "@/lib/schemas";
import { cn } from "@/lib/utils";

// ── Tab types ──────────────────────────────────────────────────────────────
type TabValue = "summary" | "draft" | "review" | "ask" | "original";

// ── Status banner ──────────────────────────────────────────────────────────
/**
 * StatusBanner — Lovable redesign uses token-based border/bg colors with
 * text-{color} design tokens. Prod tokens: text-danger, text-warning,
 * text-success, text-info, border-hairline, bg-bg-elevated.
 */
function StatusBanner({
  status,
  onRunReview,
  reviewPending,
}: {
  status: string;
  onRunReview: () => void;
  reviewPending: boolean;
}) {
  if (status === "reviewed") {
    return (
      <div className="mb-3 flex items-center gap-2 rounded-xl border border-success/30 bg-success/10 px-3 py-2 text-caption text-success">
        <span className="h-2 w-2 rounded-full bg-success shrink-0" />
        Reviewed
      </div>
    );
  }
  if (status === "reviewing") {
    return (
      <div className="mb-3 flex items-center gap-2 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-caption text-warning">
        <Loader2 className="h-3 w-3 animate-spin shrink-0" />
        Review in progress…
      </div>
    );
  }
  if (status === "extracted") {
    return (
      <div className="mb-3 flex items-center justify-between gap-2 rounded-xl border border-info/30 bg-info/10 px-3 py-2">
        <span className="text-caption text-info">Ready for review</span>
        <button
          type="button"
          onClick={onRunReview}
          disabled={reviewPending}
          className={cn(
            "rounded-lg px-3 py-1 text-caption font-semibold min-h-[32px]",
            reviewPending
              ? "bg-bg-elevated text-label-tertiary"
              : "bg-accent text-white active:bg-accent/80",
          )}
        >
          {reviewPending ? "Queuing…" : "Run review"}
        </button>
      </div>
    );
  }
  if (status === "extracting") {
    return (
      <div className="mb-3 flex items-center gap-2 rounded-xl border border-hairline bg-bg-elevated px-3 py-2 text-caption text-label-secondary">
        <Loader2 className="h-3 w-3 animate-spin shrink-0" />
        Extracting contract text…
      </div>
    );
  }
  if (status === "drafting") {
    return (
      <div className="mb-3 flex items-center gap-2 rounded-xl border border-accent/30 bg-accent/10 px-3 py-2 text-caption text-accent">
        <Loader2 className="h-3 w-3 animate-spin shrink-0" />
        Drafting contract…
      </div>
    );
  }
  if (status === "drafted") {
    return (
      <div className="mb-3 flex items-center gap-2 rounded-xl border border-accent/30 bg-accent/10 px-3 py-2 text-caption text-accent">
        <Sparkles className="h-3 w-3 shrink-0" />
        Draft ready — review with counsel before executing.
      </div>
    );
  }
  if (status === "failed") {
    return (
      <div className="mb-3 flex items-center gap-2 rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-caption text-danger">
        <AlertTriangle className="h-3 w-3 shrink-0" />
        Processing failed
      </div>
    );
  }
  return (
    <div className="mb-3 flex items-center gap-2 rounded-xl border border-hairline bg-bg-elevated px-3 py-2 text-caption text-label-secondary">
      <span className="h-2 w-2 rounded-full bg-separator shrink-0" />
      {status}
    </div>
  );
}

// ── Summary Tab ────────────────────────────────────────────────────────────
function SummaryTab({ contract }: { contract: any }) {
  if (!contract.extracted_fields) {
    return (
      <div className="rounded-2xl border border-hairline bg-bg-elevated p-6 text-center text-callout text-label-secondary">
        Awaiting extraction…
      </div>
    );
  }
  const parsed = ContractExtractionMetadataSchema.safeParse(contract.extracted_fields);
  if (!parsed.success) {
    return (
      <div className="rounded-2xl border border-hairline bg-bg-elevated p-6 text-center text-callout text-label-secondary">
        Could not render extraction data.
      </div>
    );
  }
  return <ContractExtractionView artifact={parsed.data} />;
}

// ── Review Tab ─────────────────────────────────────────────────────────────
function ReviewTab({
  contract,
  reviews,
  onRunReview,
  reviewPending,
}: {
  contract: any;
  reviews: any[];
  onRunReview: () => void;
  reviewPending: boolean;
}) {
  const latestReview = reviews[0];

  if (!latestReview) {
    return (
      <div className="rounded-2xl border border-hairline bg-bg-elevated p-6 text-center">
        <ShieldAlert className="h-8 w-8 text-label-tertiary mx-auto mb-2" />
        <p className="mb-3 text-callout text-label-secondary">
          No review has been run yet.
        </p>
        {contract.extracted_fields && (
          <button
            type="button"
            onClick={onRunReview}
            disabled={reviewPending}
            className={cn(
              "rounded-xl px-4 py-2 text-callout font-semibold min-h-[44px]",
              reviewPending
                ? "bg-bg-elevated text-label-tertiary"
                : "bg-accent text-white active:bg-accent/80",
            )}
          >
            {reviewPending ? "Queuing review…" : "Run review"}
          </button>
        )}
        {!contract.extracted_fields && (
          <p className="text-caption text-label-tertiary">
            Extraction must complete before review can run.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-caption text-label-tertiary">
        <span>Latest review</span>
        <span>·</span>
        <span>
          {new Date(latestReview.created_at).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            year: "numeric",
          })}
        </span>
      </div>
      <div className="flex gap-2 flex-wrap">
        {latestReview.severity_counts.critical > 0 && (
          <span className="rounded-lg border border-danger/30 px-2 py-1 text-caption font-semibold text-danger bg-danger/15">
            {latestReview.severity_counts.critical} Critical
          </span>
        )}
        {latestReview.severity_counts.high > 0 && (
          <span className="rounded-lg border border-warning/30 px-2 py-1 text-caption font-semibold text-warning bg-warning/15">
            {latestReview.severity_counts.high} High
          </span>
        )}
        {latestReview.severity_counts.medium > 0 && (
          <span className="rounded-lg border border-warning/20 px-2 py-1 text-caption font-semibold text-warning bg-warning/10">
            {latestReview.severity_counts.medium} Medium
          </span>
        )}
      </div>
      <p className="text-caption text-label-tertiary">
        Full review is available in the Approval Queue.
      </p>
    </div>
  );
}

// ── Ask Tab ────────────────────────────────────────────────────────────────
function AskTab({ uploadId, contract }: { uploadId: string; contract: any }) {
  const [question, setQuestion] = React.useState("");
  const [inFlight, setInFlight] = React.useState(false);

  const { data: historyData } = useContractInterpretations(uploadId);
  const interpretMutation = useInterpretContract(uploadId);

  const items = historyData?.items ?? [];
  const canAsk =
    question.trim().length > 0 &&
    question.length <= 500 &&
    !inFlight &&
    !!contract.extracted_fields;

  const handleSend = async () => {
    if (!canAsk) return;
    setInFlight(true);
    try {
      await interpretMutation.mutateAsync({ question: question.trim() });
      setQuestion("");
    } catch (err: any) {
      toast.error(err?.message ?? "Failed to get answer. Try again.");
    } finally {
      setInFlight(false);
    }
  };

  if (!contract.extracted_fields) {
    return (
      <div className="rounded-2xl border border-hairline bg-bg-elevated p-6 text-center text-callout text-label-secondary">
        Extraction must complete before you can ask questions.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Input */}
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={inFlight}
            placeholder="Ask about this contract…"
            maxLength={500}
            rows={2}
            className={cn(
              "w-full resize-none rounded-xl border border-hairline bg-bg-elevated px-3 py-2.5 text-callout text-label-primary",
              "focus:outline-none focus:ring-1 focus:ring-accent",
              inFlight && "opacity-50",
            )}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && canAsk) {
                e.preventDefault();
                handleSend();
              }
            }}
          />
          <div className="flex justify-end">
            <span
              className={cn(
                "text-caption",
                question.length > 450 ? "text-warning" : "text-label-tertiary",
              )}
            >
              {question.length}/500
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={handleSend}
          disabled={!canAsk}
          aria-label="Send question"
          className={cn(
            "flex h-11 w-11 items-center justify-center rounded-xl transition-colors no-tap-highlight",
            canAsk ? "bg-accent text-white active:bg-accent/80" : "bg-accent/40 text-white",
          )}
        >
          {inFlight ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </button>
      </div>

      {/* Q&A history (newest first) */}
      {items.length === 0 ? (
        <div className="rounded-2xl border border-hairline bg-bg-elevated p-6 text-center text-callout text-label-secondary">
          Ask a question to interpret this contract.
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <ContractInterpretationView
              key={item.interpretation_id ?? item.question}
              item={item}
              compact
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Original Tab ───────────────────────────────────────────────────────────
function OriginalTab({ contract }: { contract: any }) {
  const files: any[] = Array.isArray(contract.uploaded_files)
    ? contract.uploaded_files
    : [];
  if (files.length === 0) {
    return (
      <div className="rounded-2xl border border-hairline bg-bg-elevated p-6 text-center text-callout text-label-secondary">
        No files attached.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {files.map((f, i) => (
        <div
          key={i}
          className="flex items-center gap-3 rounded-2xl border border-hairline bg-bg-elevated p-3"
        >
          <FileText className="h-5 w-5 text-label-tertiary shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-callout text-label-primary">{f.filename}</p>
            {f.size_bytes && (
              <p className="text-caption text-label-tertiary">
                {(f.size_bytes / 1024).toFixed(0)} KB
              </p>
            )}
          </div>
          {f.minio_key && (
            <a
              href={`/api/v1/contracts/blob/${encodeURIComponent(f.minio_key)}`}
              download={f.filename}
              aria-label={`Download ${f.filename}`}
              className="rounded-lg p-2 text-accent active:bg-bg-tertiary no-tap-highlight"
            >
              <Download className="h-4 w-4" />
            </a>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Draft Tab ──────────────────────────────────────────────────────────────
function DraftTab({
  uploadId,
  contract,
  onRedraft,
}: {
  uploadId: string;
  contract: any;
  onRedraft: () => void;
}) {
  const { isLoading, draftArtifact, draftArtifactId } = useContractDraft(uploadId);

  // Drafting in progress
  if (contract.status === "drafting") {
    return (
      <div className="space-y-3">
        <DraftAttorneyBanner />
        <div className="flex items-center gap-3 rounded-2xl border border-hairline bg-bg-elevated px-4 py-4">
          <Loader2 className="h-5 w-5 animate-spin text-accent shrink-0" />
          <div>
            <p className="text-callout font-medium text-label-primary">
              Axe is drafting your contract…
            </p>
            <p className="mt-0.5 text-caption text-label-secondary">
              This usually takes a few minutes. Check back shortly.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Draft is ready
  if (contract.status === "drafted" && draftArtifactId) {
    if (isLoading) {
      return (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-label-tertiary" />
        </div>
      );
    }

    if (!draftArtifact) {
      return (
        <div className="space-y-3">
          <DraftAttorneyBanner />
          <div className="rounded-2xl border border-hairline bg-bg-elevated p-6 text-center text-callout text-label-secondary">
            Draft artifact not found.
          </div>
        </div>
      );
    }

    const parsed = ContractDraftMetadataSchema.safeParse(draftArtifact);
    return (
      <div className="space-y-3">
        <DraftAttorneyBanner />
        {parsed.success ? (
          <ContractDraftView artifact={parsed.data} />
        ) : (
          <div className="rounded-2xl border border-hairline bg-bg-elevated p-4 text-caption text-label-secondary">
            Could not render draft data.
          </div>
        )}
        <button
          type="button"
          onClick={onRedraft}
          className="flex items-center gap-1.5 rounded-xl border border-accent px-4 py-2.5 min-h-[44px] text-callout font-medium text-accent active:bg-accent/5 no-tap-highlight"
        >
          <PenLine className="h-4 w-4" />
          Revise this draft
        </button>
      </div>
    );
  }

  // Fallback
  return (
    <div className="space-y-3">
      <DraftAttorneyBanner />
      <div className="rounded-2xl border border-hairline bg-bg-elevated p-6 text-center text-callout text-label-secondary">
        Draft not yet available. Status: {contract.status}
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────
export default function ContractDetailPage() {
  const params = useParams();
  const uploadId = typeof params.upload_id === "string" ? params.upload_id : "";

  const [activeTab, setActiveTab] = React.useState<TabValue>("summary");
  const [redraftOpen, setRedraftOpen] = React.useState(false);

  const { data: contract, isLoading, error } = useContract(uploadId);
  const { data: reviewsData } = useContractReviews(uploadId);
  const reviews = reviewsData?.items ?? [];

  const dispatchReview = useDispatchContractReview(uploadId);

  const handleRunReview = async () => {
    try {
      await dispatchReview.mutateAsync();
      toast.success("Review queued — check back in a few minutes.");
    } catch (err: any) {
      toast.error(err?.message ?? "Failed to queue review.");
    }
  };

  const isDrafted = (contract as any)?.source === "drafted";

  // Build dynamic tabs — Draft tab only visible for drafted contracts
  const TABS: { label: string; value: TabValue }[] = [
    { label: "Summary", value: "summary" },
    ...(isDrafted ? [{ label: "Draft", value: "draft" as TabValue }] : []),
    { label: "Review", value: "review" },
    { label: "Ask", value: "ask" },
    { label: "Original", value: "original" },
  ];

  const title = contract
    ? (contract as any).project_label || `Contract ${uploadId.slice(0, 8)}…`
    : "Contract";

  return (
    <MobileShell>
      <TopBar
        title={title}
        left={<BackButton href="/contracts" label="Contracts" />}
      />

      {/* ModuleAgentBar — shows contract-reviewer + coordinator agents */}
      <ModuleAgentBar moduleKey="contracts" />

      <div className="mx-auto w-full max-w-[708px] px-4 pt-3 pb-16 md:max-w-4xl md:px-8">
        {isLoading && (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-label-tertiary" />
          </div>
        )}

        {error && (
          <div className="mb-3">
            <ErrorBanner message="Failed to load contract." />
          </div>
        )}

        {contract && (
          <>
            {/* Status banner */}
            <StatusBanner
              status={(contract as any).status}
              onRunReview={handleRunReview}
              reviewPending={dispatchReview.isPending}
            />

            {/* Tab bar — Lovable style: bg-bg-elevated pill, active bg-bg-primary shadow-card */}
            <div
              role="tablist"
              aria-label="Contract tabs"
              className="mb-4 flex gap-1 rounded-xl bg-bg-elevated p-1"
            >
              {TABS.map((t) => {
                const active = activeTab === t.value;
                return (
                  <button
                    key={t.value}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setActiveTab(t.value)}
                    className={cn(
                      "flex-1 rounded-lg py-2 text-caption font-semibold transition-all duration-tap ease-ios no-tap-highlight",
                      active
                        ? "bg-bg-primary text-label-primary shadow-card"
                        : "text-label-secondary active:bg-bg-primary/50",
                    )}
                  >
                    {t.label}
                  </button>
                );
              })}
            </div>

            {/* Tab content */}
            <div className="space-y-3">
              {activeTab === "summary" && <SummaryTab contract={contract} />}
              {activeTab === "draft" && isDrafted && (
                <DraftTab
                  uploadId={uploadId}
                  contract={contract}
                  onRedraft={() => setRedraftOpen(true)}
                />
              )}
              {activeTab === "review" && (
                <ReviewTab
                  contract={contract}
                  reviews={reviews}
                  onRunReview={handleRunReview}
                  reviewPending={dispatchReview.isPending}
                />
              )}
              {activeTab === "ask" && (
                <AskTab uploadId={uploadId} contract={contract} />
              )}
              {activeTab === "original" && <OriginalTab contract={contract} />}
            </div>
          </>
        )}
      </div>

      <RedraftSheet
        uploadId={uploadId}
        open={redraftOpen}
        onOpenChange={setRedraftOpen}
      />
    </MobileShell>
  );
}
