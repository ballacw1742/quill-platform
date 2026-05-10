"use client";

import * as React from "react";
import { Printer } from "lucide-react";
import { useRouter } from "next/navigation";
import { AaceClassificationSchema, CostSchedulePackageSchema } from "@/lib/schemas";
import { AaceClassificationView } from "./AaceClassificationView";
import { CostSchedulePackageView } from "./CostSchedulePackageView";
import { GenericKeyValueView } from "./GenericKeyValueView";

export interface ArtifactViewProps {
  artifact: Record<string, unknown> & { artifact_type?: string };
  mode?: "view" | "print";
  /** approval_id used for the print route — if omitted the print button is hidden */
  approvalId?: string;
}

/**
 * ArtifactView — entrypoint that dispatches to the right rich view
 * based on artifact_type.
 *
 * Props:
 *   artifact: { artifact_type: string, ...payload }
 *   mode: "view" (default) | "print"
 *   approvalId: optional — enables the Export PDF button
 */
export function ArtifactView({ artifact, mode = "view", approvalId }: ArtifactViewProps) {
  const router = useRouter();
  const artifactType = artifact?.artifact_type;
  const isPrint = mode === "print";

  if (!artifact || !artifactType) {
    return (
      <div className="rounded-xl bg-bg-tertiary px-4 py-8 text-center text-callout text-label-secondary">
        No artifact data available.
      </div>
    );
  }

  const printButton =
    !isPrint && approvalId ? (
      <div className="flex justify-end mb-3">
        <button
          type="button"
          onClick={() => router.push(`/print/artifact/${approvalId}`)}
          className="inline-flex items-center gap-1.5 rounded-lg bg-bg-elevated px-3 py-2 min-h-[44px] text-callout text-label-secondary active:bg-bg-tertiary no-tap-highlight"
          aria-label="Export PDF"
        >
          <Printer className="h-4 w-4" />
          <span>Export PDF</span>
        </button>
      </div>
    ) : null;

  // ── AACE Classification ──────────────────────────────────────────
  if (artifactType === "aace_classification") {
    const parsed = AaceClassificationSchema.safeParse(artifact);
    if (parsed.success) {
      return (
        <>
          {printButton}
          <AaceClassificationView artifact={parsed.data} mode={mode} />
        </>
      );
    }
    // Schema parse failed — fall through to generic
  }

  // ── Cost & Schedule Package ──────────────────────────────────────
  if (artifactType === "cost_schedule_package") {
    const parsed = CostSchedulePackageSchema.safeParse(artifact);
    if (parsed.success) {
      return (
        <>
          {printButton}
          <CostSchedulePackageView artifact={parsed.data} mode={mode} />
        </>
      );
    }
    // Schema parse failed — fall through to generic
  }

  // ── Generic fallback ─────────────────────────────────────────────
  return (
    <>
      {printButton}
      <GenericKeyValueView artifact={artifact} mode={mode} />
    </>
  );
}
