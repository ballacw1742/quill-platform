"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { FileUp, Plus, Trash2, X } from "lucide-react";
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
import { useUploadContract } from "@/lib/api";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const CONTRACT_TYPE_OPTIONS = [
  { value: "", label: "Auto-detect" },
  { value: "owner_gc", label: "Owner ↔ GC" },
  { value: "subcontract", label: "Subcontract" },
  { value: "change_order", label: "Change Order" },
  { value: "purchase_order", label: "Purchase Order" },
  { value: "letter_of_intent", label: "Letter of Intent" },
  { value: "nda", label: "NDA" },
  { value: "msa", label: "Master Service Agreement" },
  { value: "equipment_lease", label: "Equipment Lease" },
  { value: "insurance_certificate", label: "Insurance Certificate" },
  { value: "lien_waiver", label: "Lien Waiver" },
  { value: "other", label: "Other" },
] as const;

const ALLOWED_EXTS = ["pdf", "docx", "doc", "txt"] as const;

function extOf(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() ?? "";
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function defaultProjectLabel(): string {
  const now = new Date();
  return `Contract – ${now.toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
  })}`;
}

export type UploadContractSheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function UploadContractSheet({
  open,
  onOpenChange,
}: UploadContractSheetProps) {
  const router = useRouter();
  const [files, setFiles] = React.useState<File[]>([]);
  const [projectLabel, setProjectLabel] = React.useState<string>(() =>
    defaultProjectLabel(),
  );
  const [contractType, setContractType] = React.useState<string>("");
  const [notes, setNotes] = React.useState<string>("");
  const [dragOver, setDragOver] = React.useState(false);
  const [extensionError, setExtensionError] = React.useState<string | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  const upload = useUploadContract();

  // NB: don't list `upload` mutation object in deps — it changes every render
  // and causes an infinite re-render loop. Pin to `open` only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  React.useEffect(() => {
    if (!open) {
      setExtensionError(null);
      setDragOver(false);
      upload.reset();
    }
  }, [open]);

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
        `Unsupported file type${rejected.length > 1 ? "s" : ""}: ${rejected.join(", ")}. Accepted: PDF, DOCX, TXT.`,
      );
    } else {
      setExtensionError(null);
    }
    if (accepted.length > 0) {
      setFiles((prev) => {
        const existing = new Set(prev.map((f) => f.name));
        return [...prev, ...accepted.filter((f) => !existing.has(f.name))];
      });
    }
  }, []);

  const handleDrop = React.useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragOver(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles],
  );

  const handleRemove = (name: string) => {
    setFiles((prev) => prev.filter((f) => f.name !== name));
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    try {
      const result = await upload.mutateAsync({
        files,
        project_label: projectLabel.trim() || undefined,
        contract_type: contractType || undefined,
        notes: notes.trim() || undefined,
      });
      upload.reset();
      setFiles([]);
      setNotes("");
      setContractType("");
      setProjectLabel(defaultProjectLabel());
      onOpenChange(false);
      toast.success("Contract uploaded — starting extraction…");
      router.push(`/contracts/${result.upload_id}`);
    } catch (err: any) {
      // Error displayed via upload.error below
    }
  };

  return (
    <BottomSheet open={open} onOpenChange={onOpenChange}>
      <BottomSheetTopBar
        title="Upload Contract"
        right={
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="p-2 min-h-[44px] min-w-[44px] flex items-center justify-center rounded-lg active:bg-bg-tertiary no-tap-highlight"
            aria-label="Close"
          >
            <X className="h-5 w-5 text-label-secondary" />
          </button>
        }
      />
      <BottomSheetBody>
        <div className="space-y-4 pb-2">
          {/* Drag-drop zone */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === "Enter" && fileInputRef.current?.click()}
            aria-label="Upload contract files"
            className={cn(
              "rounded-2xl border-2 border-dashed px-6 py-8 flex flex-col items-center gap-2 cursor-pointer transition-colors no-tap-highlight",
              dragOver
                ? "border-accent bg-accent/5"
                : "border-hairline hover:border-label-tertiary",
            )}
          >
            <FileUp className="h-8 w-8 text-label-tertiary" />
            <p className="text-callout text-label-secondary text-center">
              Drag your contract here, or{" "}
              <span className="text-accent font-medium">browse files</span>
            </p>
            <p className="text-caption text-label-tertiary">PDF, DOCX, TXT</p>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.docx,.doc,.txt"
            className="hidden"
            onChange={(e) => handleFiles(e.target.files)}
          />

          {extensionError && (
            <ErrorBanner message={extensionError} />
          )}

          {/* File list */}
          {files.length > 0 && (
            <div className="space-y-1">
              {files.map((f) => (
                <div
                  key={f.name}
                  className="flex items-center gap-2 rounded-2xl border border-hairline bg-bg-elevated px-3 py-2.5"
                >
                  <span className="flex-1 text-caption text-label-primary truncate">
                    {f.name}
                  </span>
                  <span className="text-caption text-label-tertiary shrink-0">
                    {fmtBytes(f.size)}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleRemove(f.name)}
                    className="p-1 min-h-[32px] min-w-[32px] flex items-center justify-center rounded active:bg-bg-tertiary no-tap-highlight"
                    aria-label={`Remove ${f.name}`}
                  >
                    <Trash2 className="h-4 w-4 text-label-tertiary" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Project label */}
          <div className="space-y-1.5">
            <Label htmlFor="contract-label">Project label</Label>
            <Input
              id="contract-label"
              value={projectLabel}
              onChange={(e) => setProjectLabel(e.target.value)}
              placeholder="e.g. Hillcrest Renovation — Electrical Sub"
              maxLength={200}
            />
          </div>

          {/* Contract type */}
          <div className="space-y-1.5">
            <Label htmlFor="contract-type">Contract type</Label>
            <select
              id="contract-type"
              value={contractType}
              onChange={(e) => setContractType(e.target.value)}
              className={cn(
                "w-full rounded-xl bg-bg-elevated px-3 py-2.5 text-callout text-label-primary",
                "border border-hairline focus:outline-none focus:ring-1 focus:ring-accent",
                "min-h-[44px]",
              )}
            >
              {CONTRACT_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Notes */}
          <div className="space-y-1.5">
            <Label htmlFor="contract-notes">Notes (optional)</Label>
            <Textarea
              id="contract-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="e.g. Received from GC 2026-05-10. First review needed before Friday."
              rows={3}
              maxLength={2000}
            />
          </div>

          {upload.error && (
            <ErrorBanner
              message={
                (upload.error as any)?.message ?? "Upload failed. Try again."
              }
            />
          )}
        </div>
      </BottomSheetBody>
      <BottomSheetActionBar>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSubmit}
          className={cn(
            "w-full rounded-xl px-4 py-3 min-h-[50px] text-callout font-semibold transition-colors",
            canSubmit
              ? "bg-accent text-white active:bg-accent/80"
              : "bg-bg-elevated text-label-tertiary",
          )}
        >
          {upload.isPending ? "Uploading…" : "Upload Contract"}
        </button>
      </BottomSheetActionBar>
    </BottomSheet>
  );
}
