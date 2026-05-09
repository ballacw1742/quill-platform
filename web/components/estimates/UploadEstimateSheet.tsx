"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { FileUp, Plus, Trash2, Upload, X } from "lucide-react";
import {
  BottomSheet,
  BottomSheetActionBar,
  BottomSheetBody,
  BottomSheetTopBar,
} from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { ErrorBanner } from "@/components/ui/error-banner";
import { useUploadEstimate } from "@/lib/api";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

/**
 * UploadEstimateSheet — the entry point for the Cost & Schedule Package flow.
 *
 * Per COST_SCHEDULE_SPEC §"UI" / §"Upload entry point" + DESIGN_SYSTEM voice:
 *
 *   - Bottom sheet (uses the BottomSheet primitive shipped in Sprint 4).
 *   - Drag-drop area on desktop, file picker always available (mobile).
 *   - Multi-file accepted; per-file row shows name + size + format chip + remove.
 *   - Validates extensions: pdf / ifc / dxf / dwg / rvt. Other extensions are
 *     blocked with a friendly inline message.
 *   - dwg / rvt show a soft warning (Phase G.4 ships full extraction; for now
 *     we recommend converting to dxf / ifc).
 *   - project_label defaults to "QPB1 — <today>"; notes optional.
 *   - "Start estimate" → useUploadEstimate → router.push(`/estimates/{id}`).
 *
 * Voice (COPY_GUIDE):
 *   - "Class N estimate" not "AACE Class N estimate" — copy the user reads here
 *     deliberately avoids that phrase since classification hasn't run yet.
 *   - Plain English, sentence case, no jargon ("drag your drawings in").
 */

const ALLOWED_EXTS = ["pdf", "ifc", "dxf", "dwg", "rvt"] as const;
type AllowedExt = (typeof ALLOWED_EXTS)[number];

export type UploadEstimateSheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function UploadEstimateSheet({
  open,
  onOpenChange,
}: UploadEstimateSheetProps) {
  const router = useRouter();
  const [files, setFiles] = React.useState<File[]>([]);
  const [projectLabel, setProjectLabel] = React.useState<string>(() =>
    defaultProjectLabel(),
  );
  const [notes, setNotes] = React.useState<string>("");
  const [dragOver, setDragOver] = React.useState<boolean>(false);
  const [extensionError, setExtensionError] = React.useState<string | null>(
    null,
  );
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  const upload = useUploadEstimate();

  // Reset transient state when the sheet closes.
  React.useEffect(() => {
    if (!open) {
      setExtensionError(null);
      setDragOver(false);
      upload.reset();
    }
  }, [open, upload]);

  const totalBytes = files.reduce((n, f) => n + (f.size || 0), 0);
  const hasUnsupportedFormatWarning = files.some(
    (f) => extOf(f.name) === "dwg" || extOf(f.name) === "rvt",
  );
  const canSubmit = files.length > 0 && !upload.isPending;

  const handleFiles = React.useCallback((picked: FileList | File[] | null) => {
    if (!picked) return;
    const arr = Array.from(picked);
    const accepted: File[] = [];
    const rejected: string[] = [];
    for (const f of arr) {
      const ext = extOf(f.name);
      if ((ALLOWED_EXTS as readonly string[]).includes(ext)) {
        accepted.push(f);
      } else {
        rejected.push(f.name);
      }
    }
    if (rejected.length > 0) {
      setExtensionError(
        `We can read PDF, IFC, DXF, DWG, and RVT files. ` +
          `${rejected.length === 1 ? "This file isn't" : "These files aren't"} supported: ` +
          rejected.slice(0, 3).join(", ") +
          (rejected.length > 3 ? ` (+${rejected.length - 3} more)` : "") +
          ".",
      );
    } else {
      setExtensionError(null);
    }
    if (accepted.length > 0) {
      setFiles((prev) => mergeUnique(prev, accepted));
    }
  }, []);

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  };
  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    handleFiles(e.dataTransfer?.files ?? null);
  };

  const onPick = () => fileInputRef.current?.click();

  const onSubmit = async () => {
    if (!canSubmit) return;
    try {
      const result = await upload.mutateAsync({
        files,
        project_label: projectLabel.trim() || defaultProjectLabel(),
        notes: notes.trim(),
      });
      // Reset before navigating so the next open is clean.
      setFiles([]);
      setNotes("");
      setProjectLabel(defaultProjectLabel());
      onOpenChange(false);
      // Show a confirmation toast so the user has feedback even if router.push
      // is delayed or blocked by a race in client navigation.
      toast.success("Upload received — opening progress page\u2026");
      router.push(`/estimates/${encodeURIComponent(result.upload_id)}`);
    } catch (err) {
      // Surface the actual error rather than silently dropping it. Previously
      // any throw between mutateAsync's success path and router.push (e.g. a
      // schema parse error on a permissive field) was swallowed silently and
      // looked like "nothing happened" to the user.
      toast.error(
        err instanceof Error
          ? `Couldn't start the estimate: ${err.message}`
          : "Couldn't start the estimate. Try again.",
      );
    }
  };

  return (
    <BottomSheet
      open={open}
      onOpenChange={onOpenChange}
      ariaLabel="Start a new estimate from drawings"
      fullHeight
    >
      <BottomSheetTopBar
        title="New estimate"
        left={
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="text-callout text-accent active:opacity-60 no-tap-highlight px-2 py-2 -ml-2"
            aria-label="Close"
          >
            Cancel
          </button>
        }
      />
      <BottomSheetBody>
        <p className="text-body text-label-secondary mb-4">
          Drop your drawings in. Quill will read them, pick the right estimate
          class, and then build the cost and schedule.
        </p>

        {/* Drag-drop / picker */}
        <div
          onDragOver={onDragOver}
          onDragEnter={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          className={cn(
            "rounded-xl border-2 border-dashed p-6 text-center transition-state",
            dragOver
              ? "border-accent bg-accent/10"
              : "border-separator/60 bg-bg-tertiary",
          )}
        >
          <FileUp
            className="mx-auto h-7 w-7 text-accent"
            strokeWidth={1.5}
            aria-hidden="true"
          />
          <div className="mt-2 text-headline text-label-primary">
            Drag drawings here
          </div>
          <div className="mt-1 text-callout text-label-secondary">
            PDF, IFC, DXF, DWG, RVT — multiple files OK
          </div>
          <button
            type="button"
            onClick={onPick}
            className="mt-3 inline-flex h-10 items-center justify-center gap-1.5 rounded-md bg-bg-elevated px-4 text-callout text-accent active:opacity-70 no-tap-highlight"
          >
            <Upload className="h-4 w-4" /> Pick files
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.ifc,.dxf,.dwg,.rvt,application/pdf"
            className="hidden"
            onChange={(e) => {
              handleFiles(e.target.files);
              // Allow re-picking the same file later.
              if (e.target) e.target.value = "";
            }}
          />
        </div>

        {extensionError && (
          <div className="mt-3">
            <ErrorBanner message={extensionError} />
          </div>
        )}

        {hasUnsupportedFormatWarning && (
          <div className="mt-3 rounded-md bg-warning/10 px-3 py-2 text-footnote text-warning">
            DWG and RVT extraction is limited until Phase G.4 — for best
            results, convert to DXF or IFC first.
          </div>
        )}

        {/* File list */}
        {files.length > 0 && (
          <ul className="mt-4 flex flex-col gap-2">
            {files.map((f, i) => (
              <li
                key={`${f.name}-${i}`}
                className="flex items-center gap-3 rounded-md bg-bg-tertiary px-3 py-2.5"
              >
                <FormatChip ext={extOf(f.name)} />
                <div className="flex-1 min-w-0">
                  <div className="text-callout text-label-primary truncate">
                    {f.name}
                  </div>
                  <div className="text-footnote text-label-tertiary">
                    {humanBytes(f.size)}
                  </div>
                </div>
                <button
                  type="button"
                  aria-label={`Remove ${f.name}`}
                  onClick={() =>
                    setFiles((prev) => prev.filter((_, j) => j !== i))
                  }
                  className="flex h-8 w-8 items-center justify-center rounded-full text-label-tertiary active:bg-bg-elevated no-tap-highlight"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
            {files.length > 1 && (
              <li className="text-footnote text-label-tertiary px-1">
                {files.length} files · {humanBytes(totalBytes)}
              </li>
            )}
          </ul>
        )}

        {/* Project label */}
        <div className="mt-5 flex flex-col gap-1.5">
          <Label htmlFor="project_label" className="text-callout text-label-primary">
            Project label
          </Label>
          <Input
            id="project_label"
            value={projectLabel}
            onChange={(e) => setProjectLabel(e.target.value)}
            placeholder="QPB1 — DH-2 80% DD"
            autoComplete="off"
          />
          <span className="text-footnote text-label-tertiary">
            Used for the document title and downstream routing.
          </span>
        </div>

        {/* Notes */}
        <div className="mt-4 flex flex-col gap-1.5">
          <Label htmlFor="notes" className="text-callout text-label-primary">
            Notes <span className="text-label-tertiary">(optional)</span>
          </Label>
          <Textarea
            id="notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder="Anything the estimator should know — site, timing, exclusions."
          />
        </div>

        {upload.error && (
          <div className="mt-4">
            <ErrorBanner
              message={
                (upload.error as Error)?.message ||
                "We couldn't start the upload. Try again."
              }
            />
          </div>
        )}
      </BottomSheetBody>

      <BottomSheetActionBar>
        <button
          type="button"
          onClick={() => onOpenChange(false)}
          className="flex flex-1 min-h-[44px] items-center justify-center rounded-md bg-bg-elevated px-3 text-headline text-accent active:opacity-70 no-tap-highlight"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onSubmit}
          disabled={!canSubmit}
          className={cn(
            "flex flex-1 min-h-[44px] items-center justify-center gap-1.5 rounded-md px-3 text-headline no-tap-highlight transition-state",
            canSubmit
              ? "bg-accent text-white active:opacity-85"
              : "bg-accent/40 text-white/80 pointer-events-none",
          )}
        >
          {upload.isPending ? "Uploading…" : "Start estimate"}
        </button>
      </BottomSheetActionBar>
    </BottomSheet>
  );
}

/* ── Sub-components ─────────────────────────────────────────────────────── */

function FormatChip({ ext }: { ext: string }) {
  const upper = ext.toUpperCase() || "FILE";
  const tone =
    ext === "pdf"
      ? "bg-accent/10 text-accent"
      : ext === "ifc"
        ? "bg-info/10 text-info"
        : ext === "dxf"
          ? "bg-success/10 text-success"
          : ext === "dwg" || ext === "rvt"
            ? "bg-warning/10 text-warning"
            : "bg-bg-elevated text-label-secondary";
  return (
    <span
      className={cn(
        "inline-flex h-6 min-w-[36px] items-center justify-center rounded-sm px-1.5 text-caption-1 font-semibold",
        tone,
      )}
    >
      {upper}
    </span>
  );
}

/* ── Small entry button for /today's hero card ─────────────────────────── */

export function NewEstimateButton({
  onClick,
  className,
}: {
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 rounded-full bg-accent/10 px-3 py-1.5 text-footnote font-medium text-accent active:opacity-70 no-tap-highlight",
        className,
      )}
    >
      <Plus className="h-3.5 w-3.5" strokeWidth={2} />
      Estimate from drawings
    </button>
  );
}

/* ── Helpers ────────────────────────────────────────────────────────────── */

function extOf(filename: string): AllowedExt | string {
  const ext = filename.toLowerCase().split(".").pop() ?? "";
  return ext;
}

function humanBytes(n: number): string {
  if (!n || n < 0) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function mergeUnique(prev: File[], next: File[]): File[] {
  const seen = new Set(prev.map((f) => `${f.name}|${f.size}|${f.lastModified}`));
  const out = [...prev];
  for (const f of next) {
    const k = `${f.name}|${f.size}|${f.lastModified}`;
    if (!seen.has(k)) {
      out.push(f);
      seen.add(k);
    }
  }
  return out;
}

function defaultProjectLabel(): string {
  const today = new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "America/New_York",
  }).format(new Date());
  // en-CA gives YYYY-MM-DD already, which is what we want.
  return `QPB1 — ${today}`;
}
