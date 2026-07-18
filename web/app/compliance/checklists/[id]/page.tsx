"use client";

/**
 * /compliance/checklists/[id] — Checklist Detail (Sprint 4A)
 *
 * Progress bar, item list with tap-to-check, evidence URL, notes.
 *
 * Reskinned 2026-07-18: visual layer ported from Lovable
 * quill-platform-builder/src/routes/compliance.checklists.$id.tsx.
 * Prod data wiring (useChecklistDetail, useUpdateChecklistItem) preserved.
 *
 * Token map (Lovable → prod):
 *   bg-success/5, text-success/info/warning  — kept (prod tokens)
 *   bg-fill-quaternary                       — added to globals.css
 *   shadow-card inputs/textareas             — replaces border border-separator/30
 *   rounded-full save button                 — replaces rounded-xl
 *   text-accent bg-accent/10 control badge  — replaces text-purple-400 bg-purple-400/10
 *   bg-bg-elevated list + border-hairline    — replaces bg-bg-secondary border-separator/30
 *   frameworkColors: text-info/text-accent  — replaces text-blue-400/text-purple-400
 *   TopBar title with Shield icon + back btn — matches Lovable composite title
 */

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  Circle,
  ExternalLink,
  Shield,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { useChecklistDetail, useUpdateChecklistItem } from "@/lib/api";
import type { ChecklistItem } from "@/lib/schemas";

// ── Progress bar ──────────────────────────────────────────────────────────────

function ProgressBar({ checked, total }: { checked: number; total: number }) {
  const pct = total > 0 ? Math.round((checked / total) * 100) : 0;
  const color = pct >= 100 ? "bg-success" : pct >= 50 ? "bg-info" : "bg-warning";

  return (
    <div className="px-4 py-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-callout font-semibold text-label-primary">
          {checked} / {total} complete
        </span>
        <span className={cn(
          "text-headline font-bold",
          pct >= 100 ? "text-success" : pct >= 50 ? "text-info" : "text-warning",
        )}>
          {pct}%
        </span>
      </div>
      <div className="h-2 rounded-full bg-fill-quaternary overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all duration-300", color)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ── Checklist item row ────────────────────────────────────────────────────────

function ItemRow({
  item,
  checklistId,
}: {
  item: ChecklistItem;
  checklistId: string;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const [evidenceUrl, setEvidenceUrl] = React.useState(item.evidence_url ?? "");
  const [notes, setNotes] = React.useState(item.notes ?? "");
  const update = useUpdateChecklistItem(checklistId, item.id);

  const toggle = async () => {
    await update.mutateAsync({ checked: !item.checked });
  };

  const saveEvidence = async () => {
    await update.mutateAsync({
      evidence_url: evidenceUrl || null,
      notes: notes || null,
    });
  };

  return (
    <div className={cn(
      "border-b border-hairline last:border-0 transition-colors",
      item.checked && "bg-success/5",
    )}>
      {/* Main row */}
      <div className="flex items-start gap-3 px-4 py-3">
        <button
          onClick={toggle}
          disabled={update.isPending}
          className="mt-0.5 shrink-0 active:opacity-60 disabled:opacity-40"
        >
          {item.checked ? (
            <CheckCircle2 className="h-5 w-5 text-success" strokeWidth={2} />
          ) : (
            <Circle className="h-5 w-5 text-label-tertiary" strokeWidth={1.5} />
          )}
        </button>
        <div className="flex-1 min-w-0">
          {item.control_id && (
            <div className="flex items-center gap-2 mb-0.5 flex-wrap">
              <span className="inline-flex items-center rounded-md px-1.5 py-0.5 text-caption-2 font-mono font-semibold text-accent bg-accent/10">
                {item.control_id}
              </span>
            </div>
          )}
          <button
            type="button"
            onClick={() => setExpanded((e) => !e)}
            className="w-full text-left"
          >
            <span className={cn(
              "text-body font-medium block",
              item.checked ? "text-label-secondary line-through" : "text-label-primary",
            )}>
              {item.title}
            </span>
            {item.description && !expanded && (
              <span className="text-caption-1 text-label-tertiary truncate block">
                {item.description}
              </span>
            )}
          </button>

          {/* Evidence link preview */}
          {item.evidence_url && !expanded && (
            <a
              href={item.evidence_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 mt-1 text-caption-1 text-accent active:opacity-70"
            >
              <ExternalLink className="h-3 w-3" />
              Evidence
            </a>
          )}
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3">
          {item.description && (
            <p className="text-callout text-label-secondary">{item.description}</p>
          )}
          <div>
            <label className="text-caption-1 text-label-secondary mb-1 block">Evidence URL</label>
            <div className="flex gap-2">
              <input
                type="url"
                className="flex-1 rounded-xl bg-bg-elevated shadow-card px-3 py-2 text-callout text-label-primary"
                placeholder="https://…"
                value={evidenceUrl}
                onChange={(e) => setEvidenceUrl(e.target.value)}
              />
              {evidenceUrl && (
                <a
                  href={evidenceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-center h-10 w-10 rounded-full bg-accent/10 text-accent hover:bg-accent/20 active:scale-[0.98] transition-all active:opacity-70 shrink-0"
                >
                  <ExternalLink className="h-4 w-4" />
                </a>
              )}
            </div>
          </div>
          <div>
            <label className="text-caption-1 text-label-secondary mb-1 block">Notes</label>
            <textarea
              rows={2}
              className="w-full rounded-xl bg-bg-elevated shadow-card px-3 py-2 text-callout text-label-primary resize-none"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={saveEvidence}
              disabled={update.isPending}
              className="rounded-full bg-accent/10 text-accent hover:bg-accent/20 active:scale-[0.98] transition-all px-4 py-2 text-callout font-medium active:opacity-70 disabled:opacity-50"
            >
              {update.isPending ? "Saving…" : "Save"}
            </button>
            <button
              onClick={() => setExpanded(false)}
              className="rounded-xl bg-fill-quaternary text-label-secondary px-4 py-2 text-callout active:opacity-70"
            >
              Done
            </button>
          </div>
          {item.checked_at && (
            <p className="text-caption-1 text-label-tertiary">
              Checked{" "}
              {new Date(item.checked_at).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
              })}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ChecklistDetailPage() {
  const params = useParams();
  const router = useRouter();
  const checklistId = typeof params.id === "string" ? params.id : "";

  const { data: checklist, isLoading } = useChecklistDetail(checklistId);

  const frameworkColors: Record<string, string> = {
    soc2:     "text-info",
    iso27001: "text-accent",
    fisma:    "text-warning",
    nist:     "text-info",
    custom:   "text-label-secondary",
  };

  return (
    <MobileShell>
      <TopBar
        title={
          <span className="inline-flex items-center gap-2">
            <button
              onClick={() => router.push("/compliance")}
              className="flex items-center text-accent active:opacity-60"
              aria-label="Back to Compliance"
            >
              <ArrowLeft className="h-4 w-4" />
            </button>
            <Shield className="w-5 h-5 text-accent" />
            <span className="truncate">{checklist?.name ?? "Checklist"}</span>
          </span>
        }
      />

      {isLoading ? (
        <div className="px-4 pt-4 space-y-3">
          <div className="h-12 rounded-2xl bg-bg-elevated animate-pulse" />
          <div className="h-64 rounded-2xl bg-bg-elevated animate-pulse" />
        </div>
      ) : !checklist ? (
        <div className="px-4 py-16 text-center">
          <p className="text-body text-label-secondary">Checklist not found</p>
        </div>
      ) : (
        <div className="pb-24">
          {/* Meta info */}
          <div className="px-4 pt-3 flex items-center gap-2">
            <span className={cn(
              "text-caption-1 font-semibold uppercase tracking-wide",
              frameworkColors[checklist.framework] ?? "text-label-secondary",
            )}>
              {checklist.framework.toUpperCase()}
            </span>
            <span className="text-caption-1 text-label-tertiary">·</span>
            <span className="text-caption-1 text-label-secondary capitalize">{checklist.status}</span>
            {checklist.campus_id && (
              <>
                <span className="text-caption-1 text-label-tertiary">·</span>
                <span className="text-caption-1 text-label-secondary">
                  Campus {checklist.campus_id.slice(0, 8)}…
                </span>
              </>
            )}
          </div>

          {/* Progress */}
          <ProgressBar
            checked={checklist.checked_items}
            total={checklist.total_items}
          />

          {/* Items */}
          {checklist.items.length === 0 ? (
            <div className="px-4 py-12 text-center">
              <CheckCircle2 className="mx-auto h-10 w-10 text-label-tertiary mb-3" strokeWidth={1} />
              <p className="text-body text-label-secondary">No items in this checklist</p>
              <p className="text-callout text-label-tertiary mt-1">
                Add items via the API or import them from a framework template
              </p>
            </div>
          ) : (
            <div className="mx-4 rounded-2xl bg-bg-elevated border border-hairline overflow-hidden">
              {checklist.items.map((item) => (
                <ItemRow key={item.id} item={item} checklistId={checklistId} />
              ))}
            </div>
          )}
        </div>
      )}
    </MobileShell>
  );
}
