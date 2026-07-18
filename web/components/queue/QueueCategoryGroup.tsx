"use client";

/**
 * QueueCategoryGroup.tsx — collapsible section for one workflow category
 * in the Queue page. Lovable-reskinned visual layer; all prod behaviour
 * (onApprove, onReject swipe gates, ApprovalRow) preserved.
 *
 * Renders:
 *   • A header button (≥ 44px touch target) with:
 *       - Chevron that rotates right→down when open
 *       - Category display label
 *       - Pending-count badge (only when pendingCount > 0)
 *       - Total item count
 *   • Collapsible list of ApprovalRow items
 *
 * Multiple sections can be open simultaneously (no accordion constraint).
 */

import * as React from "react";
import { ChevronRight } from "lucide-react";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/Collapsible";
import { Badge } from "@/components/ui/badge";
import { ApprovalRow } from "./ApprovalRow";
import type { QueueCategory } from "@/lib/queue-categories";
import { cn } from "@/lib/utils";

interface QueueCategoryGroupProps {
  category: QueueCategory;
  open: boolean;
  onToggle: () => void;
  onOpen: (id: string) => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}

export function QueueCategoryGroup({
  category,
  open,
  onToggle,
  onOpen,
  onApprove,
  onReject,
}: QueueCategoryGroupProps) {
  return (
    <Collapsible open={open} onOpenChange={onToggle}>
      <CollapsibleTrigger
        open={open}
        onToggle={onToggle}
        className="border-b border-hairline bg-bg-elevated px-4 py-0 w-full"
        aria-label={`${category.label}, ${category.items.length} items${
          category.pendingCount > 0 ? `, ${category.pendingCount} pending` : ""
        }, ${open ? "expanded" : "collapsed"}`}
      >
        <div className="flex flex-1 items-center gap-2 py-3 min-h-[44px]">
          {/* Chevron: points right when collapsed, rotates 90° (down) when open */}
          <ChevronRight
            className={cn(
              "h-4 w-4 text-label-tertiary shrink-0 transition-transform duration-200",
              open && "rotate-90",
            )}
            aria-hidden="true"
          />

          {/* Category label */}
          <span className="text-callout font-semibold text-label-primary flex-1 truncate text-left">
            {category.label}
          </span>

          {/* Pending badge (only when > 0) */}
          {category.pendingCount > 0 && (
            <Badge
              variant="default"
              className="text-caption-2 h-5 px-1.5 min-w-[20px] bg-accent text-white shrink-0 hover:bg-accent"
            >
              {category.pendingCount}
            </Badge>
          )}

          {/* Total item count */}
          <span className="text-footnote text-label-tertiary shrink-0">
            {category.items.length}
          </span>
        </div>
      </CollapsibleTrigger>

      <CollapsibleContent open={open}>
        <ul className="divide-y divide-separator/30" role="list">
          {category.items.map((item) => (
            <li key={item.approval_id}>
              <ApprovalRow
                item={item}
                onOpen={onOpen}
                onApprove={onApprove}
                onReject={onReject}
              />
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}
