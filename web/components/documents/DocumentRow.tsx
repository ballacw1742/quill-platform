"use client";

import * as React from "react";
import { formatDistanceToNowStrict } from "date-fns";
import { ListRow } from "@/components/ui/list-row";
import {
  artifactTypeIcon,
  artifactTypeLabel,
  artifactTypeTone,
} from "@/lib/document-meta";
import { cn } from "@/lib/utils";
import type { DocumentSummary, DocumentSearchHit } from "@/lib/schemas";

/**
 * DocumentRow — list-row variant for the /documents tab.
 *
 *   ┌──────────────────────────────────────────────────────────────┐
 *   │ [icon]  Title (text-headline)                  [type chip]  >│
 *   │         Agent · 2 days ago                                  │
 *   │         (optional snippet — search results only)            │
 *   └──────────────────────────────────────────────────────────────┘
 *
 * Tap opens /documents/[id]. Per MOBILE_UX_SPEC §"List rows", tap target =
 * full row; chevron is automatic via ListRow.
 *
 * Accepts either a DocumentSummary (list view) or DocumentSearchHit
 * (search view, which also carries an optional `snippet`).
 */
export function DocumentRow({
  doc,
  showSnippet = false,
  hideDivider = false,
}: {
  doc: DocumentSummary | DocumentSearchHit;
  showSnippet?: boolean;
  hideDivider?: boolean;
}) {
  const Icon = artifactTypeIcon(doc.artifact_type);
  const tone = artifactTypeTone(doc.artifact_type);
  const label = artifactTypeLabel(
    doc.artifact_type,
    doc.metadata as Record<string, unknown> | undefined,
  );

  const created = doc.created_at ? new Date(doc.created_at) : null;
  const ago =
    created && !Number.isNaN(created.getTime())
      ? formatDistanceToNowStrict(created, { addSuffix: true })
      : "";

  const agent =
    (doc.agent_display_name && doc.agent_display_name.trim()) || doc.agent_id;

  const subtitle = (
    <span className="truncate">
      {agent}
      {ago && (
        <>
          <span className="text-label-tertiary"> · </span>
          {ago}
        </>
      )}
    </span>
  );

  // Search-result snippet: rendered in the footer slot so it sits below the
  // standard subtitle without competing with the row's title. The Document
  // schemas use `.passthrough()` so we cast `snippet` explicitly to string.
  const rawSnippet =
    showSnippet && "snippet" in doc
      ? (doc as DocumentSearchHit).snippet
      : undefined;
  const snippet =
    typeof rawSnippet === "string" && rawSnippet.length > 0 ? (
      <span className="block truncate text-footnote text-label-tertiary">
        {rawSnippet}
      </span>
    ) : null;

  return (
    <ListRow
      icon={<Icon className="h-4 w-4" strokeWidth={1.75} />}
      iconTone={tone}
      title={doc.title || "Untitled"}
      subtitle={subtitle}
      footer={snippet}
      chip={<TypeChip>{label}</TypeChip>}
      href={`/documents/${encodeURIComponent(doc.id)}`}
      hideDivider={hideDivider}
      ariaLabel={`${label}: ${doc.title}`}
    />
  );
}

function TypeChip({ children }: { children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm px-1.5 py-0.5",
        "bg-bg-elevated text-label-secondary",
        "text-caption-1 font-medium",
      )}
    >
      {children}
    </span>
  );
}
