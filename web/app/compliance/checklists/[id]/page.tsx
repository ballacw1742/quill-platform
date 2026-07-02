"use client";

/**
 * /compliance/checklists/[id] — Checklist Detail (Sprint 4A)
 *
 * Progress bar, item list with tap-to-check, evidence URL, notes.
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
  const color = pct >= 100 ? "bg-green-400" : pct >= 50 ? "bg-blue-400" : "bg-orange-400";

  return (
    <div className="px-4 py-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-callout font-semibold text-label-primary">
          {checked} / {total} complete
        </span>
        <span className={cn(
          "text-headline font-bold",
          pct >= 100 ? "text-green-400" : pct >= 50 ? "text-blue-400" : "text-orange-400",
        )}>
          {pct}%
        </span>
      </div>
      <div className="h-2 rounded-full bg-bg-elevated overflow-hidden">
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
    await update.mutateAsync({ evidence_url: evidenceUrl, notes });
  };

  return (
    <div className={cn(
      "border-b border-separator/20 last:border-0 transition-colors",
      item.checked && "bg-green-400/5",
    )}>
      {/* Main row */}
      <div className="flex items-start gap-3 px-4 py-3">
        <button
          onClick={toggle}
          disabled={update.isPending}
          className="mt-0.5 shrink-0 active:opacity-60 disabled:opacity-40"
        >
          {item.checked ? (
            <CheckCircle2 className="h-5 w-5 text-green-400" strokeWidth={2} />
          ) : (
            <Circle className="h-5 w-5 text-label-quaternary" strokeWidth={1.5} />
          )}
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5 flex-wrap">
            {item.control_id && (
              <span className="inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-mono font-semibold text-purple-400 bg-purple-400/10">
                {item.control_id}
              </span>
            )}
          </div>
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
                className="flex-1 rounded-xl bg-bg-elevated border border-separator/30 px-3 py-2 text-callout text-label-primary"
                placeholder="https://…"
                value={evidenceUrl}
                onChange={(e) => setEvidenceUrl(e.target.value)}
              />
              {evidenceUrl && (
                <a
                  href={evidenceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-center h-10 w-10 rounded-xl bg-accent/10 text-accent active:opacity-70 shrink-0"
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
              className="w-full rounded-xl bg-bg-elevated border border-separator/30 px-3 py-2 text-callout text-label-primary resize-none"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={saveEvidence}
              disabled={update.isPending}
              className="rounded-xl bg-accent/10 text-accent px-4 py-2 text-callout font-medium active:opacity-70 disabled:opacity-50"
            >
              {update.isPending ? "Saving…" : "Save"}
            </button>
            <button
              onClick={() => setExpanded(false)}
              className="rounded-xl bg-bg-elevated text-label-secondary px-4 py-2 text-callout active:opacity-70"
            >
              Done
            </button>
          </div>
          {item.checked_at && (
            <p className="text-caption-1 text-label-quaternary">
              Checked {new Date(item.checked_at).toLocaleDateString("en-US", {
                month: "short", day: "numeric", year: "numeric",
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
    soc2:    "text-blue-400",
    iso27001: "text-purple-400",
    fisma:   "text-orange-400",
    nist:    "text-teal-400",
    custom:  "text-label-secondary",
  };

  return (
    <MobileShell>
      <TopBar
        title={checklist?.name ?? "Checklist"}
        left={
          <button
            onClick={() => router.back()}
            className="flex items-center gap-1.5 text-accent active:opacity-60"
          >
            <ArrowLeft className="h-4 w-4" />
            <span className="text-callout">Back</span>
          </button>
        }
        right={
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/10">
            <Shield className="h-4 w-4 text-accent" strokeWidth={1.75} />
          </span>
        }
      />

      {isLoading ? (
        <div className="px-4 pt-4 space-y-3">
          <div className="h-12 rounded-2xl bg-bg-secondary animate-pulse" />
          <div className="h-64 rounded-2xl bg-bg-secondary animate-pulse" />
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
            <span className="text-caption-1 text-label-quaternary">·</span>
            <span className="text-caption-1 text-label-secondary capitalize">{checklist.status}</span>
            {checklist.campus_id && (
              <>
                <span className="text-caption-1 text-label-quaternary">·</span>
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
              <CheckCircle2 className="mx-auto h-10 w-10 text-label-quaternary mb-3" strokeWidth={1} />
              <p className="text-body text-label-secondary">No items in this checklist</p>
              <p className="text-callout text-label-tertiary mt-1">
                Add items via the API or import them from a framework template
              </p>
            </div>
          ) : (
            <div className="mx-4 rounded-2xl bg-bg-secondary border border-separator/30 overflow-hidden">
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
