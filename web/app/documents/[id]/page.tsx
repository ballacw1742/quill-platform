"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { format } from "date-fns";
import {
  Download,
  ExternalLink,
  FileText,
  MoreHorizontal,
  Share2,
} from "lucide-react";
import { toast } from "sonner";
import { MobileShell, TopBar, BackButton } from "@/components/layout/MobileShell";
import { AgentBadge } from "@/components/queue/AgentBadge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { MarkdownBody } from "@/components/documents/MarkdownBody";
import { ExportSheet } from "@/components/documents/ExportSheet";
import { MoreMenuSheet } from "@/components/documents/MoreMenuSheet";
import { ArtifactView } from "@/components/artifacts/ArtifactView";
import { useDocument, useDocumentDriveLink } from "@/lib/api";
import {
  artifactTypeLabel,
  artifactTypeTone,
  artifactTypeIcon,
} from "@/lib/document-meta";
import { displayName } from "@/lib/agent-meta";
import { cn } from "@/lib/utils";

/**
 * /documents/[id] — Phase D.2 detail screen.
 *
 * Per DOCUMENTS_SPEC \u00a7"Document detail screen `/documents/[id]`":
 *   \u2022 TopBar: back chevron \u2190 /documents, title, right-side menu (\u2022\u2022\u2022).
 *   \u2022 Hero: title (text-title-2), agent badge, type chip, created/approved metadata.
 *   \u2022 Body: rendered markdown with sanitization (MarkdownBody primitive).
 *   \u2022 Sticky bottom action bar: Open in Drive | Export | Share.
 *
 * The bar is content-aware:
 *   - "Open in Drive" is enabled only if the Drive link is ready; while pending
 *     it shows "Drive link still uploading\u2026" and is disabled (per spec).
 *   - "Share" uses navigator.share when available (mobile), else copies a
 *     deep link to the clipboard with a toast.
 *   - "Export" opens ExportSheet (Markdown / PDF / Word).
 */
export default function DocumentDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id ? decodeURIComponent(params.id) : "";

  const { data: doc, isLoading, error, refetch } = useDocument(id);
  const { data: driveLink } = useDocumentDriveLink(id);

  const [exportOpen, setExportOpen] = React.useState(false);
  const [moreOpen, setMoreOpen] = React.useState(false);

  const handleShare = React.useCallback(async () => {
    if (!doc) return;
    const shareUrl =
      typeof window !== "undefined"
        ? `${window.location.origin}/documents/${encodeURIComponent(doc.id)}`
        : "";
    const shareData = {
      title: doc.title,
      text: doc.summary || doc.title,
      url: shareUrl,
    };
    if (
      typeof navigator !== "undefined" &&
      typeof navigator.share === "function"
    ) {
      try {
        await navigator.share(shareData);
        return;
      } catch (e) {
        // User cancelled or platform threw; fall through to clipboard.
        if (e instanceof Error && e.name === "AbortError") return;
      }
    }
    if (
      typeof navigator !== "undefined" &&
      navigator.clipboard?.writeText
    ) {
      try {
        await navigator.clipboard.writeText(shareUrl);
        toast.success("Link copied to clipboard");
        return;
      } catch {
        // fall through
      }
    }
    toast.error("Couldn't share. Copy the URL manually.");
  }, [doc]);

  return (
    <MobileShell>
      <TopBar
        title={doc?.title || "Document"}
        left={<BackButton href="/documents" label="Documents" />}
        right={
          <button
            type="button"
            aria-label="More options"
            onClick={() => setMoreOpen(true)}
            className="flex h-11 w-11 items-center justify-center text-accent active:opacity-60 no-tap-highlight"
            disabled={!doc}
          >
            <MoreHorizontal className="h-5 w-5" />
          </button>
        }
      />

      <div className="flex min-h-[calc(100dvh-200px)] flex-col bg-bg">
        {error ? (
          <div className="px-4 pt-4">
            <ErrorBanner
              message="Couldn't load this document. Try again."
              onRetry={() => refetch()}
            />
          </div>
        ) : isLoading ? (
          <DetailSkeleton />
        ) : !doc ? (
          <EmptyState
            icon={<FileText />}
            title="We couldn't find that document."
            subtitle="It may have been removed, or the link is wrong."
          />
        ) : (
          <>
            {/* Hero */}
            <header className="px-4 pt-4 pb-3 bg-bg">
              <h1 className="text-title-2 text-label-primary">{doc.title}</h1>
              {doc.summary && (
                <p className="mt-1 text-body text-label-secondary">
                  {doc.summary}
                </p>
              )}
              <div className="mt-3 flex items-center gap-2 flex-wrap">
                <AgentBadge agentId={doc.agent_id} />
                <span className="text-callout text-label-secondary">
                  {doc.agent_display_name?.trim() || displayName(doc.agent_id)}
                </span>
                <TypePill
                  type={doc.artifact_type}
                  metadata={doc.metadata as Record<string, unknown> | undefined}
                />
              </div>
              <Metadata
                createdAt={doc.created_at}
                approvedAt={doc.approved_at}
              />
            </header>

            {/* Body */}
            <article className="flex-1 px-4 pb-32 bg-bg">
              {doc.metadata ? (
                <ArtifactView
                  artifact={{
                    artifact_type: doc.artifact_type,
                    artifact_id: doc.artifact_id,
                    title: doc.title,
                    summary: doc.summary,
                    body_markdown: doc.body_markdown,
                    ...(doc.metadata as Record<string, unknown>),
                  }}
                  mode="view"
                />
              ) : (
                <MarkdownBody markdown={doc.body_markdown || ""} />
              )}
            </article>
          </>
        )}
      </div>

      {/* Sticky bottom action bar */}
      {doc && (
        <ActionBar
          driveUrl={driveLink?.url ?? doc.drive_url ?? null}
          onExport={() => setExportOpen(true)}
          onShare={handleShare}
        />
      )}

      <ExportSheet
        documentId={doc?.id ?? null}
        open={exportOpen}
        onOpenChange={setExportOpen}
      />

      <MoreMenuSheet
        open={moreOpen}
        onOpenChange={setMoreOpen}
        doc={doc ?? null}
      />
    </MobileShell>
  );
}

/* ── Sub-components ──────────────────────────────────────────────────────── */

function TypePill({
  type,
  metadata,
}: {
  type: string;
  metadata?: Record<string, unknown>;
}) {
  const Icon = artifactTypeIcon(type);
  const tone = artifactTypeTone(type);
  const label = artifactTypeLabel(type, metadata);
  const toneClass: Record<string, string> = {
    neutral: "bg-bg-elevated text-label-secondary",
    accent: "bg-accent/10 text-accent",
    info: "bg-info/10 text-info",
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning",
    danger: "bg-danger/10 text-danger",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm px-2 py-0.5",
        toneClass[tone] ?? toneClass.neutral,
        "text-caption-1 font-medium",
      )}
    >
      <Icon className="h-3 w-3" strokeWidth={1.75} aria-hidden="true" />
      {label}
    </span>
  );
}

function Metadata({
  createdAt,
  approvedAt,
}: {
  createdAt?: string | null;
  approvedAt?: string | null;
}) {
  const fmt = (iso?: string | null) => {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return format(d, "MMM d, yyyy 'at' h:mm a");
  };
  const created = fmt(createdAt);
  const approved = fmt(approvedAt);
  if (!created && !approved) return null;
  return (
    <div className="mt-2 flex flex-col gap-0.5 text-footnote text-label-tertiary">
      {created && <span>Created {created}</span>}
      {approved && <span>Approved {approved}</span>}
    </div>
  );
}

function ActionBar({
  driveUrl,
  onExport,
  onShare,
}: {
  driveUrl: string | null;
  onExport: () => void;
  onShare: () => void;
}) {
  return (
    <div
      className={cn(
        "fixed left-0 right-0 z-30",
        "border-t border-separator/40 bg-bg/95 backdrop-blur-md",
        "px-4 pt-3 pb-safe",
        // Sit above the bottom tab bar (49px + safe area).
        "bottom-[calc(49px+env(safe-area-inset-bottom,0px))]",
      )}
    >
      <div className="flex items-stretch gap-2 pb-3">
        {driveUrl && (
          <ActionButton
            icon={<ExternalLink className="h-4 w-4" />}
            label="Open in Drive"
            onClick={() => {
              window.open(driveUrl, "_blank", "noopener,noreferrer");
            }}
          />
        )}
        <ActionButton
          icon={<Download className="h-4 w-4" />}
          label="Export"
          onClick={onExport}
          variant="primary"
        />
        <ActionButton
          icon={<Share2 className="h-4 w-4" />}
          label="Share"
          onClick={onShare}
        />
      </div>
    </div>
  );
}

function ActionButton({
  icon,
  label,
  onClick,
  variant = "ghost",
  disabled,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  variant?: "primary" | "ghost";
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex flex-1 min-h-[44px] items-center justify-center gap-1.5 rounded-md px-3 text-headline no-tap-highlight transition-state",
        variant === "primary"
          ? "bg-accent text-white active:opacity-85"
          : "bg-bg-elevated text-accent active:opacity-70",
        disabled && "opacity-50 pointer-events-none",
      )}
    >
      {icon}
      <span className="truncate">{label}</span>
    </button>
  );
}

function DetailSkeleton() {
  return (
    <div className="px-4 pt-4 space-y-3" aria-label="Loading document">
      <span className="block h-6 w-3/4 rounded-sm bg-bg-elevated animate-shimmer" />
      <span className="block h-4 w-2/3 rounded-sm bg-bg-elevated animate-shimmer" />
      <span className="block h-4 w-1/2 rounded-sm bg-bg-elevated animate-shimmer" />
      <div className="pt-4 space-y-2">
        <span className="block h-3.5 w-full rounded-sm bg-bg-elevated animate-shimmer" />
        <span className="block h-3.5 w-5/6 rounded-sm bg-bg-elevated animate-shimmer" />
        <span className="block h-3.5 w-11/12 rounded-sm bg-bg-elevated animate-shimmer" />
        <span className="block h-3.5 w-4/6 rounded-sm bg-bg-elevated animate-shimmer" />
      </div>
    </div>
  );
}
