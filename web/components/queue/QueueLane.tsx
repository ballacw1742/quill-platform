"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ApprovalCard } from "./ApprovalCard";
import { LANE_META } from "./laneMeta";
import type { ApprovalItem, Lane } from "@/lib/schemas";

export function QueueLane({
  lane,
  items,
  className,
}: {
  lane: Lane;
  items: ApprovalItem[];
  className?: string;
}) {
  const meta = LANE_META[lane];
  return (
    <section className={cn("flex min-h-0 flex-col rounded-lg border bg-card/40", className)}>
      <header className="flex items-center justify-between border-b px-3 py-2">
        <div className="flex items-center gap-2">
          <span className={cn("inline-block h-2 w-2 rounded-full", meta.color)} />
          <h2 className="text-sm font-semibold">{meta.label}</h2>
        </div>
        <Badge variant="secondary" className="font-mono text-xs">
          {items.length}
        </Badge>
      </header>
      <p className="border-b px-3 py-1.5 text-[11px] text-muted-foreground">{meta.description}</p>
      <ScrollArea className="flex-1">
        <div className="space-y-2 p-3">
          {items.length === 0 ? (
            <div className="flex h-32 items-center justify-center rounded-md border border-dashed text-xs text-muted-foreground">
              Queue clear.
            </div>
          ) : (
            items.map((item) => <ApprovalCard key={item.approval_id} item={item} />)
          )}
        </div>
      </ScrollArea>
    </section>
  );
}
