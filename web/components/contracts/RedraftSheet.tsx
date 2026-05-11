"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Plus, Trash2 } from "lucide-react";
import {
  BottomSheet,
  BottomSheetActionBar,
  BottomSheetBody,
  BottomSheetTopBar,
} from "@/components/ui/sheet";
import { useRedraftContract } from "@/lib/api";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

type KeyTermOverride = { topic: string; requirement: string };

export type RedraftSheetProps = {
  uploadId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function RedraftSheet({ uploadId, open, onOpenChange }: RedraftSheetProps) {
  const router = useRouter();
  const [revisionNotes, setRevisionNotes] = React.useState("");
  const [overrides, setOverrides] = React.useState<KeyTermOverride[]>([]);

  const redraft = useRedraftContract(uploadId);

  // Reset state when sheet closes — pin useEffect dep to [open] only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  React.useEffect(() => {
    if (!open) {
      setRevisionNotes("");
      setOverrides([]);
      redraft.reset();
    }
  }, [open]);

  const canSubmit = revisionNotes.trim().length > 0 && !redraft.isPending;

  const handleConfirm = async () => {
    if (!canSubmit) return;
    try {
      const result: any = await redraft.mutateAsync({
        revision_notes: revisionNotes.trim(),
        key_terms_overrides:
          overrides.filter((o) => o.topic && o.requirement).length > 0
            ? overrides.filter((o) => o.topic && o.requirement)
            : undefined,
      });
      toast.success("Revision request created. Axe is re-drafting your contract…");
      onOpenChange(false);
      if (result?.upload_id) {
        router.push(`/contracts/${result.upload_id}`);
      }
    } catch (err: any) {
      toast.error(err?.message ?? "Failed to request redraft.");
    }
  };

  return (
    <BottomSheet open={open} onOpenChange={onOpenChange}>
      <BottomSheetTopBar title="Revise Draft" onClose={() => onOpenChange(false)} />

      <BottomSheetBody>
        <div className="space-y-4">
          <div>
            <label className="text-caption text-label-tertiary mb-1 block">
              Revision Notes *
            </label>
            <textarea
              value={revisionNotes}
              onChange={(e) => setRevisionNotes(e.target.value)}
              disabled={redraft.isPending}
              placeholder="Describe the changes you want. E.g. 'Add liquidated damages at $500/day, tighten the payment terms, reduce retainage to 5%.'"
              rows={4}
              className="w-full rounded-xl border border-separator bg-bg-primary px-3 py-2.5 text-callout text-label-primary focus:outline-none focus:ring-1 focus:ring-accent resize-none disabled:opacity-50"
            />
          </div>

          <div className="space-y-2">
            <label className="text-caption text-label-tertiary block">
              Key Term Overrides (optional)
            </label>
            <p className="text-caption text-label-tertiary">
              Override or add specific clause requirements from the original request.
            </p>
            {overrides.map((override, i) => (
              <div
                key={i}
                className="flex items-start gap-2 rounded-xl border border-separator bg-bg-elevated px-3 py-2.5"
              >
                <div className="flex-1 space-y-1.5">
                  <input
                    type="text"
                    value={override.topic}
                    onChange={(e) => {
                      const next = [...overrides];
                      next[i] = { ...override, topic: e.target.value };
                      setOverrides(next);
                    }}
                    placeholder={`Topic ${i + 1} (e.g. liquidated_damages)`}
                    className="w-full rounded-lg border border-separator bg-bg-primary px-2.5 py-1.5 text-caption text-label-primary focus:outline-none focus:ring-1 focus:ring-accent"
                  />
                  <input
                    type="text"
                    value={override.requirement}
                    onChange={(e) => {
                      const next = [...overrides];
                      next[i] = { ...override, requirement: e.target.value };
                      setOverrides(next);
                    }}
                    placeholder="New requirement"
                    className="w-full rounded-lg border border-separator bg-bg-primary px-2.5 py-1.5 text-caption text-label-primary focus:outline-none focus:ring-1 focus:ring-accent"
                  />
                </div>
                <button
                  type="button"
                  onClick={() => setOverrides(overrides.filter((_, j) => j !== i))}
                  className="p-1.5 rounded-lg active:bg-bg-tertiary no-tap-highlight text-label-tertiary"
                  aria-label={`Remove override ${i + 1}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={() => setOverrides([...overrides, { topic: "", requirement: "" }])}
              className="flex items-center gap-1.5 text-callout text-accent active:opacity-70 no-tap-highlight py-1"
            >
              <Plus className="h-4 w-4" />
              Add term override
            </button>
          </div>

          {redraft.isError && (
            <div className="text-caption text-red-600 rounded-lg bg-red-50 border border-red-200 px-3 py-2">
              {(redraft.error as Error)?.message ?? "Failed to request redraft."}
            </div>
          )}
        </div>
      </BottomSheetBody>

      <BottomSheetActionBar>
        <button
          type="button"
          onClick={() => onOpenChange(false)}
          className="rounded-xl border border-separator bg-bg-elevated px-4 py-3 min-h-[44px] text-callout font-medium text-label-primary active:bg-bg-tertiary no-tap-highlight"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleConfirm}
          disabled={!canSubmit}
          className={cn(
            "flex-1 rounded-xl px-4 py-3 min-h-[44px] text-callout font-semibold transition-colors no-tap-highlight",
            canSubmit
              ? "bg-accent text-white active:bg-accent/80"
              : "bg-bg-elevated text-label-tertiary",
          )}
        >
          {redraft.isPending ? "Creating…" : "Request Revision"}
        </button>
      </BottomSheetActionBar>
    </BottomSheet>
  );
}

export default RedraftSheet;
