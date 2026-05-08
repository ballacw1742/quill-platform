/**
 * lib/document-meta.ts — UI display metadata for Documents (Phase D).
 *
 * Per COPY_GUIDE.md voice: plain English, sentence case, no developer jargon.
 * The API uses canonical artifact_type values (`status_update`,
 * `coordinator_artifact`, `pm_analysis`, `comms_draft`, `knowledge_entry`).
 * The UI translates each to:
 *
 *   - a lucide icon (artifactTypeIcon)
 *   - a tone token (artifactTypeTone) for icon backgrounds
 *   - a plain-English label (artifactTypeLabel) — coordinator_artifact further
 *     refines based on metadata.kind ("SOP" / "RACI" / "Agenda" / etc.)
 *
 * Unknown artifact_types fall back to a generic FileText icon and a
 * pretty-cased label so we never leak a raw token into the UI.
 */

import {
  BarChart3,
  ClipboardList,
  FileText,
  Lightbulb,
  Mail,
  Newspaper,
  type LucideIcon,
} from "lucide-react";
import { prettyCase } from "@/lib/agent-meta";

/* ── Icon mapping ────────────────────────────────────────────────────────── */

const ARTIFACT_ICON: Record<string, LucideIcon> = {
  status_update: Newspaper,
  coordinator_artifact: ClipboardList,
  pm_analysis: BarChart3,
  comms_draft: Mail,
  knowledge_entry: Lightbulb,
};

export function artifactTypeIcon(type: string | null | undefined): LucideIcon {
  if (!type) return FileText;
  return ARTIFACT_ICON[type] ?? FileText;
}

/* ── Tone (icon container colour) ─────────────────────────────────────────── */

export type ArtifactTone =
  | "neutral"
  | "accent"
  | "info"
  | "success"
  | "warning"
  | "danger";

const ARTIFACT_TONE: Record<string, ArtifactTone> = {
  // Distinct but calm — matches DESIGN_SYSTEM tone palette.
  status_update: "accent", // weekly/regular cadence → systemBlue
  coordinator_artifact: "info", // process docs → systemIndigo
  pm_analysis: "warning", // analyses often surface risk → systemOrange
  comms_draft: "success", // outbound comms → systemGreen
  knowledge_entry: "neutral", // institutional memory → label-secondary
};

export function artifactTypeTone(type: string | null | undefined): ArtifactTone {
  if (!type) return "neutral";
  return ARTIFACT_TONE[type] ?? "neutral";
}

/* ── Plain-English label ──────────────────────────────────────────────────── */

const ARTIFACT_LABEL: Record<string, string> = {
  status_update: "Status update",
  coordinator_artifact: "Process doc",
  pm_analysis: "Analysis",
  comms_draft: "Comms draft",
  knowledge_entry: "Knowledge entry",
};

/**
 * For coordinator_artifact, refine the label based on metadata.kind so a SOP
 * doesn't read as "Process doc" when we know it's specifically a SOP.
 *
 * Accepted metadata.kind values (lowercased): sop, raci, agenda, action_items,
 * action-items, process. Anything else falls back to "Process doc".
 */
const COORDINATOR_KIND_LABEL: Record<string, string> = {
  sop: "SOP",
  raci: "RACI",
  agenda: "Agenda",
  action_items: "Action items",
  "action-items": "Action items",
  actionitems: "Action items",
  process: "Process",
  procedure: "Procedure",
  policy: "Policy",
};

export function artifactTypeLabel(
  type: string | null | undefined,
  metadata?: Record<string, unknown> | null,
): string {
  if (!type) return "Document";
  if (type === "coordinator_artifact") {
    const kind = (metadata?.kind as string | undefined)?.toLowerCase().trim();
    if (kind && COORDINATOR_KIND_LABEL[kind]) {
      return COORDINATOR_KIND_LABEL[kind];
    }
    return ARTIFACT_LABEL.coordinator_artifact;
  }
  return ARTIFACT_LABEL[type] ?? prettyCase(type) ?? "Document";
}

/* ── Segmented control filters ───────────────────────────────────────────── */

/**
 * The /documents segmented control has 6 segments per DOCUMENTS_SPEC.md
 * §"Section header (segmented)":
 *   All | Status updates | Process docs | Analyses | Comms drafts | Knowledge
 *
 * "all" is the catch-all; the others map 1:1 to artifact_type values.
 */
export type DocumentFilterValue =
  | "all"
  | "status_update"
  | "coordinator_artifact"
  | "pm_analysis"
  | "comms_draft"
  | "knowledge_entry";

export const DOCUMENT_FILTER_OPTIONS: ReadonlyArray<{
  value: DocumentFilterValue;
  label: string;
}> = [
  { value: "all", label: "All" },
  { value: "status_update", label: "Status" },
  { value: "coordinator_artifact", label: "Process" },
  { value: "pm_analysis", label: "Analyses" },
  { value: "comms_draft", label: "Comms" },
  { value: "knowledge_entry", label: "Knowledge" },
];

/** Maps a DocumentFilterValue to the API `artifact_type` query (or undefined). */
export function filterToArtifactType(
  v: DocumentFilterValue,
): string | undefined {
  return v === "all" ? undefined : v;
}
