"use client";

import * as React from "react";
import { AlertTriangle, Check } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { JsonBlock } from "./JsonBlock";

function diffLines(a: string, b: string): { kind: "same" | "add" | "del" | "ctx"; text: string }[] {
  // Simple LCS-free diff: line-by-line zip with markers. Good enough for a
  // human-eyeball diff in a modal; not designed for huge payloads.
  const al = a.split("\n");
  const bl = b.split("\n");
  const max = Math.max(al.length, bl.length);
  const out: { kind: "same" | "add" | "del" | "ctx"; text: string }[] = [];
  for (let i = 0; i < max; i++) {
    const x = al[i];
    const y = bl[i];
    if (x === y) out.push({ kind: "same", text: x ?? "" });
    else {
      if (x !== undefined) out.push({ kind: "del", text: x });
      if (y !== undefined) out.push({ kind: "add", text: y });
    }
  }
  return out;
}

export function EditPayloadDialog({
  open,
  onOpenChange,
  original,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  original: Record<string, unknown>;
  onConfirm: (edited: Record<string, unknown>) => void;
}) {
  const originalText = React.useMemo(() => JSON.stringify(original, null, 2), [original]);
  const [text, setText] = React.useState(originalText);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setText(originalText);
      setError(null);
    }
  }, [open, originalText]);

  const parsed = React.useMemo(() => {
    try {
      const v = JSON.parse(text);
      if (typeof v !== "object" || v === null || Array.isArray(v)) {
        return { ok: false, err: "Payload must be a JSON object." };
      }
      return { ok: true, value: v as Record<string, unknown> };
    } catch (e) {
      return { ok: false, err: e instanceof Error ? e.message : "Invalid JSON" };
    }
  }, [text]);

  const diff = React.useMemo(() => {
    if (!parsed.ok) return [];
    return diffLines(originalText, JSON.stringify(parsed.value, null, 2));
  }, [parsed, originalText]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>Edit payload before approval</DialogTitle>
          <DialogDescription>
            Edit the agent&apos;s proposed payload in-place. Both the edit and the original are
            captured in the audit trail.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1.5">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
              Edited JSON
            </div>
            <Textarea
              spellCheck={false}
              className="h-72 font-mono text-xs"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            {!parsed.ok && (
              <div className="flex items-center gap-1.5 text-[11px] text-destructive">
                <AlertTriangle className="h-3 w-3" /> {parsed.err}
              </div>
            )}
          </div>
          <div className="space-y-1.5">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
              Diff vs original
            </div>
            <div className="h-72 overflow-auto rounded-md border bg-muted/40 p-2 font-mono text-[11px] leading-relaxed scrollbar-thin">
              {diff.length === 0 ? (
                <div className="text-muted-foreground">—</div>
              ) : (
                diff.map((l, i) => (
                  <div
                    key={i}
                    className={
                      l.kind === "add"
                        ? "bg-success/10 text-success"
                        : l.kind === "del"
                          ? "bg-destructive/10 text-destructive line-through"
                          : "text-muted-foreground"
                    }
                  >
                    <span className="select-none pr-2 opacity-60">
                      {l.kind === "add" ? "+" : l.kind === "del" ? "−" : " "}
                    </span>
                    {l.text}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">Show original payload</summary>
          <div className="mt-2">
            <JsonBlock value={original} maxHeight={200} />
          </div>
        </details>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!parsed.ok}
            onClick={() => {
              if (parsed.ok && parsed.value) {
                onConfirm(parsed.value);
              } else {
                setError(parsed.err ?? "Invalid");
              }
            }}
          >
            <Check className="h-4 w-4" /> Apply edits & continue
          </Button>
        </DialogFooter>
        {error && <div className="text-xs text-destructive">{error}</div>}
      </DialogContent>
    </Dialog>
  );
}
