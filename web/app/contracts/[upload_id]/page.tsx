"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, Download, FileText, Loader2, PenLine, Send } from "lucide-react";
import { toast } from "sonner";
import { MobileShell, TopBar, BackButton } from "@/components/layout/MobileShell";
import { ErrorBanner } from "@/components/ui/error-banner";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { ContractExtractionView } from "@/components/artifacts/ContractExtractionView";
import { ContractReviewView } from "@/components/artifacts/ContractReviewView";
import { ContractInterpretationView } from "@/components/artifacts/ContractInterpretationView";
import { ContractDraftView } from "@/components/artifacts/ContractDraftView";
import { DraftAttorneyBanner } from "@/components/contracts/DraftAttorneyBanner";
import { RedraftSheet } from "@/components/contracts/RedraftSheet";
import {
  useContract,
  useContractReviews,
  useContractInterpretations,
  useDispatchContractReview,
  useInterpretContract,
  useContractDraft,
} from "@/lib/api";
import { ContractExtractionMetadataSchema, ContractReviewMetadataSchema, ContractDraftMetadataSchema } from "@/lib/schemas";
import { cn } from "@/lib/utils";

// ── Tab types ──────────────────────────────────────────────────────────────
type TabValue = "summary" | "draft" | "review" | "ask" | "original";

// ── Status banner ──────────────────────────────────────────────────────────
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
      <div className="flex items-center gap-2 rounded-xl bg-green-50 border border-green-200 px-3 py-2 text-caption text-green-700">
        <span className="h-2 w-2 rounded-full bg-green-500 shrink-0" />
        Reviewed
      </div>
    );
  }
  if (status === "reviewing") {
    return (
      <div className="flex items-center gap-2 rounded-xl bg-amber-50 border border-amber-200 px-3 py-2 text-caption text-amber-700">
        <Loader2 className="h-3 w-3 animate-spin shrink-0" />
        Review in progress…
      </div>
    );
  }
  if (status === "extracted") {
    return (
      <div className="flex items-center justify-between gap-2 rounded-xl bg-blue-50 border border-blue-200 px-3 py-2">
        <span className="text-caption text-blue-700">Ready for review</span>
        <button
          type="button"
          onClick={onRunReview}
          disabled={reviewPending}
          className={cn(
            "text-caption font-semibold px-3 py-1.5 rounded-lg min-h-[32px]",
            reviewPending
              ? "text-label-tertiary bg-bg-elevated"
              : "text-white bg-blue-600 active:bg-blue-700",
          )}
        >
          {reviewPending ? "Queuing…" : "Run review"}
        </button>
      </div>
    );
  }
  if (status === "extracting") {
    return (
      <div className="flex items-center gap-2 rounded-xl bg-bg-elevated border border-separator px-3 py-2 text-caption text-label-secondary">
        <Loader2 className="h-3 w-3 animate-spin shrink-0" />
        Extracting contract text…
      </div>
    );
  }
  if (status === "failed") {
    return (
      <div className="flex items-center gap-2 rounded-xl bg-red-50 border border-red-200 px-3 py-2 text-caption text-red-700">
        <AlertTriangle className="h-3 w-3 shrink-0" />
        Processing failed
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 rounded-xl bg-bg-elevated border border-separator px-3 py-2 text-caption text-label-secondary">
      <span className="h-2 w-2 rounded-full bg-separator shrink-0" />
      {status}
    </div>
  );
}

// ── Summary Tab ────────────────────────────────────────────────────────────
function SummaryTab({ contract }: { contract: any }) {
  if (!contract.extracted_fields) {
    return (
      <div className="rounded-xl bg-bg-elevated px-4 py-8 text-center text-callout text-label-secondary">
        Extraction not yet complete. Check back shortly.
      </div>
    );
  }
  const parsed = ContractExtractionMetadataSchema.safeParse(contract.extracted_fields);
  if (!parsed.success) {
    return (
      <div className="rounded-xl bg-bg-elevated px-4 py-8 text-center text-callout text-label-secondary">
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
      <div className="space-y-4">
        <div className="rounded-xl bg-bg-elevated px-4 py-8 text-center">
          <FileText className="h-8 w-8 text-label-tertiary mx-auto mb-2" />
          <p className="text-callout text-label-secondary mb-4">
            No review yet for this contract.
          </p>
          {contract.extracted_fields && (
            <button
              type="button"
              onClick={onRunReview}
              disabled={reviewPending}
              className={cn(
                "px-4 py-2 rounded-xl text-callout font-semibold min-h-[44px]",
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
      </div>
    );
  }

  // The review artifact is stored in the Document's meta — we'll render
  // from the review list item's severity_counts as a placeholder if the
  // full artifact isn't available here.
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-caption text-label-tertiary">
        <span>Latest review</span>
        <span>·</span>
        <span>{new Date(latestReview.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span>
      </div>
      <div className="flex gap-2 flex-wrap">
        {latestReview.severity_counts.critical > 0 && (
          <span className="text-caption font-semibold text-red-700 bg-red-50 rounded-lg px-2 py-1">
            {latestReview.severity_counts.critical} Critical
          </span>
        )}
        {latestReview.severity_counts.high > 0 && (
          <span className="text-caption font-semibold text-orange-700 bg-orange-50 rounded-lg px-2 py-1">
            {latestReview.severity_counts.high} High
          </span>
        )}
        {latestReview.severity_counts.medium > 0 && (
          <span className="text-caption font-semibold text-amber-700 bg-amber-50 rounded-lg px-2 py-1">
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
  const canAsk = question.trim().length > 0 && question.length <= 500 && !inFlight && !!contract.extracted_fields;

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
      <div className="rounded-xl bg-bg-elevated px-4 py-8 text-center text-callout text-label-secondary">
        Extraction must complete before you can ask questions.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Input */}
      <div className="flex gap-2 items-end">
        <div className="flex-1">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={inFlight}
            placeholder="Ask a question about this contract…"
            maxLength={500}
            rows={2}
            className={cn(
              "w-full rounded-xl bg-bg-elevated px-3 py-2.5 text-callout text-label-primary",
              "border border-separator focus:outline-none focus:ring-1 focus:ring-accent",
              "resize-none",
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
                question.length > 450 ? "text-amber-500" : "text-label-tertiary",
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
          className={cn(
            "rounded-xl p-3 min-h-[44px] min-w-[44px] flex items-center justify-center transition-colors",
            canAsk
              ? "bg-accent text-white active:bg-accent/80"
              : "bg-bg-elevated text-label-tertiary",
          )}
          aria-label="Send question"
        >
          {inFlight ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : (
            <Send className="h-5 w-5" />
          )}
        </button>
      </div>

      {/* Q&A history (newest first) */}
      {items.length > 0 && (
        <div className="rounded-xl bg-bg-elevated overflow-hidden">
          <p className="px-4 py-3 text-callout font-semibold text-label-primary border-b border-separator">
            Past Questions
          </p>
          <div className="px-4">
            {items.map((item) => (
              <ContractInterpretationView
                key={item.interpretation_id ?? item.question}
                item={item}
                compact
              />
            ))}
          </div>
        </div>
      )}

      {items.length === 0 && (
        <div className="rounded-xl bg-bg-elevated px-4 py-6 text-center text-caption text-label-secondary">
          Ask your first question above.
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
      <div className="rounded-xl bg-bg-elevated px-4 py-8 text-center text-callout text-label-secondary">
        No files available.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {files.map((f, i) => (
        <div
          key={i}
          className="flex items-center gap-3 rounded-xl bg-bg-elevated px-4 py-3"
        >
          <FileText className="h-5 w-5 text-label-tertiary shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-callout text-label-primary truncate">{f.filename}</p>
            {f.size_bytes && (
              <p className="text-caption text-label-tertiary">
                {(f.size_bytes / 1024).toFixed(1)} KB
              </p>
            )}
          </div>
          {f.minio_key && (
            <a
              href={`/api/v1/contracts/blob/${encodeURIComponent(f.minio_key)}`}
              download={f.filename}
              className="p-2 rounded-lg active:bg-bg-tertiary no-tap-highlight"
              aria-label={`Download ${f.filename}`}
            >
              <Download className="h-4 w-4 text-accent" />
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
      <div className="space-y-4">
        <DraftAttorneyBanner />
        <div className="flex items-center gap-3 rounded-xl bg-bg-elevated border border-separator px-4 py-4">
          <Loader2 className="h-5 w-5 animate-spin text-accent shrink-0" />
          <div>
            <p className="text-callout font-medium text-label-primary">
              Axe is drafting your contract…
            </p>
            <p className="text-caption text-label-secondary mt-0.5">
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
        <div className="space-y-4">
          <DraftAttorneyBanner />
          <div className="rounded-xl bg-bg-elevated px-4 py-6 text-center text-callout text-label-secondary">
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
          <div className="rounded-xl bg-bg-elevated px-4 py-4 text-caption text-label-secondary">
            Could not render draft data.
          </div>
        )}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onRedraft}
            className="flex items-center gap-1.5 rounded-xl border border-accent px-4 py-2.5 min-h-[44px] text-callout font-medium text-accent active:bg-accent/5 no-tap-highlight"
          >
            <PenLine className="h-4 w-4" />
            Revise this draft
          </button>
        </div>
      </div>
    );
  }

  // Fallback
  return (
    <div className="space-y-4">
      <DraftAttorneyBanner />
      <div className="rounded-xl bg-bg-elevated px-4 py-6 text-center text-callout text-label-secondary">
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
    ? (contract as any).project_label ||
      `Contract ${uploadId.slice(0, 8)}…`
    : "Contract";

  return (
    <MobileShell>
      <TopBar
        title={title}
        left={
          <BackButton href="/contracts" label="Contracts" />
        }
      />

      <div className="flex-1 overflow-y-auto">
        {isLoading && (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-label-tertiary" />
          </div>
        )}

        {error && (
          <div className="px-4 pt-4">
            <ErrorBanner message="Failed to load contract." />
          </div>
        )}

        {contract && (
          <>
            {/* Status banner */}
            <div className="px-4 pt-3 pb-2">
              <StatusBanner
                status={(contract as any).status}
                onRunReview={handleRunReview}
                reviewPending={dispatchReview.isPending}
              />
            </div>

            {/* Tab selector */}
            <div className="px-4 pb-3">
              <SegmentedControl
                options={TABS}
                value={activeTab}
                onChange={(v) => setActiveTab(v as TabValue)}
              />
            </div>

            {/* Tab content */}
            <div className="px-4 pb-8 space-y-3">
              {activeTab === "summary" && (
                <SummaryTab contract={contract} />
              )}
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
              {activeTab === "original" && (
                <OriginalTab contract={contract} />
              )}
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
