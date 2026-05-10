"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { useApproval } from "@/lib/api";
import { ArtifactView } from "@/components/artifacts/ArtifactView";

/**
 * /print/artifact/[approval_id] — print-friendly artifact page.
 *
 * Renders <ArtifactView mode="print" /> with all collapsible sections
 * forced open, then fires window.print() on mount.
 *
 * iOS Safari → Share → Save to Files (PDF) works natively.
 * Desktop Chrome/Safari → Print → Save as PDF.
 *
 * Print CSS is in globals.css (@media print).
 */
export default function PrintArtifactPage() {
  const params = useParams<{ approval_id: string }>();
  const approvalId = params?.approval_id
    ? decodeURIComponent(params.approval_id)
    : "";

  const { data: item, isLoading } = useApproval(approvalId);

  // Fire print dialog once the content is loaded.
  React.useEffect(() => {
    if (item) {
      // Small delay to allow fonts/images to settle.
      const t = setTimeout(() => {
        if (typeof window !== "undefined") {
          window.print();
        }
      }, 400);
      return () => clearTimeout(t);
    }
  }, [item]);

  const artifact = item
    ? ((item.proposed_action.payload as Record<string, unknown>)
        ?.artifact as Record<string, unknown> | undefined)
    : null;

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-callout text-label-secondary">
        Loading…
      </div>
    );
  }

  if (!item || !artifact) {
    return (
      <div className="flex min-h-screen items-center justify-center text-callout text-label-secondary">
        Artifact not found.
      </div>
    );
  }

  return (
    <div className="print-root min-h-screen bg-white p-6 font-sans">
      {/* Print header */}
      <div className="print-header mb-6 pb-4 border-b border-gray-200 print:block hidden">
        <div className="text-lg font-semibold text-gray-900">{item.summary ?? "Approval artifact"}</div>
        <div className="text-sm text-gray-500 mt-1">
          {item.workflow} · {item.approval_id} · Printed {new Date().toLocaleDateString()}
        </div>
      </div>

      {/* Screen-only header with back button */}
      <div className="mb-4 print:hidden flex items-center justify-between">
        <button
          type="button"
          onClick={() => typeof window !== "undefined" && window.history.back()}
          className="text-callout text-accent active:opacity-60 no-tap-highlight"
        >
          ← Back
        </button>
        <button
          type="button"
          onClick={() => typeof window !== "undefined" && window.print()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-callout text-white active:opacity-85 no-tap-highlight"
        >
          Save as PDF
        </button>
      </div>

      <ArtifactView artifact={artifact} mode="print" />
    </div>
  );
}
