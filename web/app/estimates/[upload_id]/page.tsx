"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleX,
  FileText,
  Loader2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { MobileShell, TopBar, BackButton } from "@/components/layout/MobileShell";
import { ErrorBanner } from "@/components/ui/error-banner";
import { EmptyState } from "@/components/ui/empty-state";
import { useEstimateStatus, useStartEstimation } from "@/lib/api";
import { challengePasskey } from "@/lib/auth";
import {
  AaceClassificationSchema,
  isEstimateInFlight,
  type AaceClassification,
  type EstimateStatus,
  type EstimateUploadFileEntry,
} from "@/lib/schemas";
import { useDocument } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * /estimates/[upload_id] — progress + classification approval page.
 *
 * Per COST_SCHEDULE_SPEC §"UI" / §"Estimate progress page" + MOBILE_UX_SPEC
 * stack-page conventions:
 *
 *   - TopBar: back chevron + title (project_label or "New estimate").
 *   - useEstimateStatus polls every 4s while in flight; stops on done|failed.
 *   - File list with extraction status badges (✓ ok / ⚠ partial / ✗ failed)
 *     and per-file extraction summary.
 *   - Status banner adapts to current state.
 *   - When a classification artifact id arrives we hydrate it via
 *     useDocument(id) and surface: Class badge, confidence gauge,
 *     supporting evidence, missing-for-next-class. The "Approve and generate
 *     estimate" button triggers the WebAuthn passkey ceremony then
 *     useStartEstimation.
 *   - When the package artifact id arrives, link to /documents/{id}.
 *
 * Voice (COPY_GUIDE):
 *   - "Class N estimate" not "AACE Class N estimate".
 *   - Plain status banners ("Reading your drawings.").
 */

export default function EstimateProgressPage() {
  const params = useParams<{ upload_id: string }>();
  const uploadId = params?.upload_id ? decodeURIComponent(params.upload_id) : "";

  const { data: status, error, refetch, isLoading } = useEstimateStatus(uploadId);
  const classificationId = status?.classification_artifact_id ?? null;
  const packageId = status?.package_artifact_id ?? null;

  const { data: classificationDoc } = useDocument(classificationId);
  const classification = React.useMemo<AaceClassification | null>(() => {
    if (!classificationDoc) return null;
    const parsed = AaceClassificationSchema.safeParse({
      artifact_type: classificationDoc.artifact_type,
      artifact_id: classificationDoc.artifact_id,
      title: classificationDoc.title,
      summary: classificationDoc.summary,
      body_markdown: classificationDoc.body_markdown,
      metadata: classificationDoc.metadata ?? {},
      citations: [],
      confidence: 0,
    });
    return parsed.success ? parsed.data : null;
  }, [classificationDoc]);

  const startEstimation = useStartEstimation(uploadId);
  const [submitting, setSubmitting] = React.useState(false);

  const title = status?.project_label?.trim() || "New estimate";

  const onApprove = async () => {
    if (!classification || !uploadId) return;
    setSubmitting(true);
    try {
      // Re-auth via passkey to mint a one-shot action assertion. The estimate
      // start-action is a Lane-2 (single-sig) decision per COST_SCHEDULE_SPEC.
      const intent = {
        approval_id: `estimate:${uploadId}`,
        decision: "approve" as const,
      };
      let assertion: string | undefined;
      try {
        const res = await challengePasskey(intent);
        assertion = res.auth_assertion;
      } catch (e) {
        // If the user cancels or no passkey is available, still try the call —
        // the API will reject with 401 if it requires the assertion.
        // eslint-disable-next-line no-console
        console.warn("estimate: passkey ceremony failed, retrying without", e);
      }
      await startEstimation.mutateAsync(
        assertion ? { passkey_assertion: assertion } : undefined,
      );
      toast.success("Approved. Quill is building the estimate.");
    } catch (e) {
      toast.error(
        e instanceof Error
          ? e.message
          : "We couldn't approve the classification. Try again.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <MobileShell>
      <TopBar
        title={title}
        left={<BackButton href="/estimates" label="Estimates" />}
      />

      <div className="flex min-h-[calc(100dvh-200px)] flex-col bg-bg pb-24">
        {error ? (
          <div className="px-4 pt-4">
            <ErrorBanner
              message="Couldn't load this estimate. Try again."
              onRetry={() => refetch()}
            />
          </div>
        ) : isLoading && !status ? (
          <ProgressSkeleton />
        ) : !status ? (
          <EmptyState
            icon={<FileText />}
            title="We couldn't find that upload."
            subtitle="The link may be wrong, or the upload was removed."
          />
        ) : (
          <>
            <StatusBanner status={status.status} errorMessage={status.error_message} />

            {/* File list */}
            <section className="px-4 pt-4">
              <h2 className="text-headline text-label-primary mb-2">
                Drawings
              </h2>
              <ul className="flex flex-col gap-2">
                {status.uploaded_files.length === 0 ? (
                  <li className="text-callout text-label-tertiary">
                    No files attached.
                  </li>
                ) : (
                  status.uploaded_files.map((f, i) => (
                    <FileRow key={`${f.filename}-${i}`} file={f} />
                  ))
                )}
              </ul>
            </section>

            {/* Classification panel */}
            {classificationId && (
              <ClassificationPanel
                classification={classification}
                isStale={!classificationDoc}
                packageId={packageId}
                status={status.status}
                onApprove={onApprove}
                submitting={submitting || startEstimation.isPending}
              />
            )}

            {/* Done state */}
            {packageId && (
              <section className="px-4 pt-6">
                <Link
                  href={`/documents/${encodeURIComponent(packageId)}`}
                  className="flex items-center gap-3 rounded-xl bg-accent/10 px-4 py-4 active:opacity-70 no-tap-highlight"
                >
                  <span className="flex h-9 w-9 items-center justify-center rounded-md bg-accent/20 text-accent">
                    <Sparkles className="h-4 w-4" />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-headline text-accent">
                      View estimate package
                    </div>
                    <div className="text-callout text-label-secondary">
                      Cost rows, schedule, risks, and basis are ready.
                    </div>
                  </div>
                  <ChevronRight className="h-4 w-4 text-accent" />
                </Link>
              </section>
            )}
          </>
        )}
      </div>
    </MobileShell>
  );
}

/* ── Status banner ──────────────────────────────────────────────────────── */

function StatusBanner({
  status,
  errorMessage,
}: {
  status: EstimateStatus["status"];
  errorMessage?: string | null;
}) {
  const meta = statusMeta(status);
  const inFlight = isEstimateInFlight(status);
  return (
    <div className="px-4 pt-4">
      <div
        className={cn(
          "flex items-center gap-3 rounded-xl px-4 py-3.5",
          meta.bg,
        )}
      >
        <span className={cn("flex h-7 w-7 items-center justify-center rounded-md", meta.iconBg)}>
          {inFlight ? (
            <Loader2 className={cn("h-4 w-4 animate-spin", meta.iconColor)} />
          ) : (
            <meta.Icon className={cn("h-4 w-4", meta.iconColor)} />
          )}
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-headline text-label-primary">{meta.title}</div>
          <div className="text-callout text-label-secondary">
            {errorMessage && status === "failed" ? errorMessage : meta.subtitle}
          </div>
        </div>
      </div>
    </div>
  );
}

function statusMeta(status: string) {
  const palette = {
    info: {
      bg: "bg-info/10",
      iconBg: "bg-info/15",
      iconColor: "text-info",
      Icon: Loader2,
    },
    accent: {
      bg: "bg-accent/10",
      iconBg: "bg-accent/15",
      iconColor: "text-accent",
      Icon: ShieldCheck,
    },
    success: {
      bg: "bg-success/10",
      iconBg: "bg-success/15",
      iconColor: "text-success",
      Icon: CheckCircle2,
    },
    danger: {
      bg: "bg-danger/10",
      iconBg: "bg-danger/15",
      iconColor: "text-danger",
      Icon: AlertTriangle,
    },
    neutral: {
      bg: "bg-bg-tertiary",
      iconBg: "bg-bg-elevated",
      iconColor: "text-label-secondary",
      Icon: Loader2,
    },
  } as const;
  switch (status) {
    case "queued":
      return { ...palette.neutral, title: "Queued", subtitle: "Waiting to start." };
    case "extracting":
      return { ...palette.info, title: "Reading your drawings.", subtitle: "Pulling text, IFC entities, and DXF layers." };
    case "classifying":
      return { ...palette.info, title: "Classifying design maturity.", subtitle: "Choosing the right estimate class." };
    case "awaiting_classification_approval":
      return { ...palette.accent, title: "Classification ready for review.", subtitle: "Approve to generate the estimate." };
    case "estimating":
      return { ...palette.info, title: "Building the estimate.", subtitle: "Cost rows, schedule, and risks are coming together." };
    case "awaiting_package_approval":
      return { ...palette.accent, title: "Estimate package ready.", subtitle: "Final review before publishing." };
    case "done":
      return { ...palette.success, title: "Estimate published.", subtitle: "Open the document to explore." };
    case "failed":
      return { ...palette.danger, title: "Something went wrong.", subtitle: "Retry the upload or contact support." };
    default:
      return { ...palette.neutral, title: status || "Working…", subtitle: "" };
  }
}

/* ── File row ───────────────────────────────────────────────────────────── */

function FileRow({ file }: { file: EstimateUploadFileEntry }) {
  const status = file.extraction_status;
  const { Icon, color, label } = (() => {
    switch (status) {
      case "ok":
        return { Icon: CircleCheck, color: "text-success", label: "Read" };
      case "partial":
        return { Icon: CircleAlert, color: "text-warning", label: "Partial" };
      case "failed":
        return { Icon: CircleX, color: "text-danger", label: "Failed" };
      default:
        return { Icon: Loader2, color: "text-label-tertiary animate-spin", label: "Reading…" };
    }
  })();
  return (
    <li className="flex items-center gap-3 rounded-md bg-bg-tertiary px-3 py-2.5">
      <Icon className={cn("h-4 w-4 shrink-0", color)} aria-label={label} />
      <div className="flex-1 min-w-0">
        <div className="text-callout text-label-primary truncate">
          {file.filename}
        </div>
        <div className="text-footnote text-label-tertiary truncate">
          {file.kind?.toUpperCase() || "FILE"} · {humanBytes(file.size_bytes)}
          {file.extraction_summary ? ` · ${file.extraction_summary}` : ""}
        </div>
      </div>
    </li>
  );
}

/* ── Classification panel ───────────────────────────────────────────────── */

function ClassificationPanel({
  classification,
  isStale,
  packageId,
  status,
  onApprove,
  submitting,
}: {
  classification: AaceClassification | null;
  isStale: boolean;
  packageId: string | null;
  status: EstimateStatus["status"];
  onApprove: () => Promise<void> | void;
  submitting: boolean;
}) {
  const showApproveCta =
    !packageId &&
    !!classification &&
    (status === "awaiting_classification_approval" ||
      status === "classifying");

  return (
    <section className="px-4 pt-6">
      <div className="rounded-xl bg-bg-tertiary p-4 shadow-card">
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-title-3 text-label-primary">Classification</h2>
          {isStale && (
            <span className="text-footnote text-label-tertiary">
              Hydrating…
            </span>
          )}
        </div>

        {!classification ? (
          <div className="text-callout text-label-secondary">
            We&apos;re picking the right class. This usually finishes in a minute or two.
          </div>
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <ClassBadge cls={classification.metadata.class} />
              <span className="text-callout text-label-secondary">
                {Math.round(
                  (classification.metadata.design_maturity_estimate_pct ?? 0),
                )}
                % design maturity
              </span>
              <span className="ml-auto text-footnote text-label-tertiary tabular-nums">
                {Math.round((classification.confidence ?? 0) * 100)}% confidence
              </span>
            </div>

            {classification.metadata.accuracy_range && (
              <div className="mt-1 text-footnote text-label-tertiary">
                Accuracy band {classification.metadata.accuracy_range.low_pct}% /
                +{classification.metadata.accuracy_range.high_pct}%
              </div>
            )}

            {/* Evidence */}
            {classification.metadata.supporting_evidence.length > 0 && (
              <div className="mt-4">
                <div className="text-headline text-label-primary mb-2">
                  Why this class
                </div>
                <ul className="flex flex-col gap-1.5">
                  {classification.metadata.supporting_evidence
                    .slice(0, 8)
                    .map((e, i) => (
                      <li key={i} className="flex items-start gap-2">
                        <span className="mt-0.5 inline-block h-2 w-12 shrink-0 rounded-full bg-bg-elevated overflow-hidden">
                          <span
                            className="block h-full bg-accent"
                            style={{
                              width: `${Math.round((e.score || 0) * 100)}%`,
                            }}
                          />
                        </span>
                        <span className="text-footnote text-label-secondary">
                          <span className="text-label-primary">
                            {prettyCategory(e.category)}.
                          </span>{" "}
                          {e.evidence}
                        </span>
                      </li>
                    ))}
                </ul>
              </div>
            )}

            {/* Missing-for-next-class */}
            {classification.metadata.missing_for_next_class.length > 0 && (
              <div className="mt-4">
                <div className="text-headline text-label-primary mb-2">
                  To unlock the next class
                </div>
                <ul className="flex flex-col gap-1.5">
                  {classification.metadata.missing_for_next_class
                    .slice(0, 8)
                    .map((m, i) => (
                      <li key={i} className="text-footnote text-label-secondary">
                        <span className="text-label-primary">{m.deliverable}.</span>{" "}
                        {m.rationale}{" "}
                        <span className="text-label-tertiary">
                          (would unlock Class {m.would_unlock_class})
                        </span>
                      </li>
                    ))}
                </ul>
              </div>
            )}

            {showApproveCta && (
              <div className="mt-5 flex flex-col gap-2">
                <button
                  type="button"
                  onClick={() => onApprove()}
                  disabled={submitting}
                  className={cn(
                    "flex min-h-[44px] items-center justify-center rounded-md bg-accent px-4 text-headline text-white active:opacity-85 no-tap-highlight",
                    submitting && "opacity-70 pointer-events-none",
                  )}
                >
                  {submitting
                    ? "Approving…"
                    : `Approve Class ${classification.metadata.class} & build estimate`}
                </button>
                <span className="text-footnote text-label-tertiary text-center">
                  Confirms with your passkey before kicking off the
                  estimator-scheduler.
                </span>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}

function ClassBadge({ cls }: { cls: string }) {
  return (
    <span className="inline-flex items-center rounded-md bg-accent px-2.5 py-1 text-headline font-semibold text-white">
      Class {cls}
    </span>
  );
}

function ProgressSkeleton() {
  return (
    <div className="px-4 pt-4 space-y-3" aria-label="Loading estimate">
      <span className="block h-12 w-full rounded-xl bg-bg-elevated animate-shimmer" />
      <span className="block h-4 w-2/3 rounded-sm bg-bg-elevated animate-shimmer" />
      <div className="pt-2 space-y-2">
        <span className="block h-12 w-full rounded-md bg-bg-elevated animate-shimmer" />
        <span className="block h-12 w-full rounded-md bg-bg-elevated animate-shimmer" />
      </div>
    </div>
  );
}

function humanBytes(n: number): string {
  if (!n || n < 0) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function prettyCategory(cat: string): string {
  return cat.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
