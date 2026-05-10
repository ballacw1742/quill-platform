"use client";

import * as React from "react";
import { ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";

export interface CitationEntry {
  kind?: string;
  ref?: string;
  note?: string;
  url?: string;
  excerpt?: string;
}

export function Citation({ citation }: { citation: CitationEntry }) {
  const inner = (
    <div className="flex items-start gap-3 px-4 py-3 min-h-[44px]">
      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-bg-elevated text-label-tertiary">
        <ExternalLink className="h-3.5 w-3.5" />
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-callout text-label-primary">
          {citation.kind && (
            <span className="text-label-tertiary text-footnote mr-1.5">
              {citation.kind}
            </span>
          )}
          <span className="font-mono text-footnote">{citation.ref}</span>
        </div>
        {citation.note && (
          <div className="text-footnote text-label-secondary mt-0.5">
            {citation.note}
          </div>
        )}
      </div>
    </div>
  );

  if (citation.url) {
    return (
      <a
        href={citation.url}
        target="_blank"
        rel="noreferrer"
        className="block no-tap-highlight active:bg-bg-elevated/60"
      >
        {inner}
      </a>
    );
  }
  return <div>{inner}</div>;
}

export function CitationList({
  citations,
  className,
}: {
  citations: CitationEntry[];
  className?: string;
}) {
  if (!citations || citations.length === 0) return null;
  return (
    <div className={cn("space-y-1", className)}>
      <div className="text-caption-1 uppercase tracking-wider text-label-tertiary mb-1">
        Citations
      </div>
      <div className="overflow-hidden rounded-lg bg-bg-tertiary divide-y divide-separator/40">
        {citations.map((c, i) => (
          <Citation key={i} citation={c} />
        ))}
      </div>
    </div>
  );
}
