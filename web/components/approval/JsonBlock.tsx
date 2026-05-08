"use client";

import * as React from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function JsonBlock({
  value,
  className,
  collapsible = false,
  defaultCollapsed = false,
  maxHeight,
}: {
  value: unknown;
  className?: string;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  maxHeight?: number;
}) {
  const text = React.useMemo(() => safeStringify(value), [value]);
  const [collapsed, setCollapsed] = React.useState(defaultCollapsed && collapsible);
  const [copied, setCopied] = React.useState(false);
  return (
    <div className={cn("relative rounded-md border bg-muted/40", className)}>
      <div className="flex items-center justify-between border-b px-2 py-1">
        <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
          json
        </span>
        <div className="flex items-center gap-1">
          {collapsible && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-[11px]"
              onClick={() => setCollapsed((c) => !c)}
            >
              {collapsed ? "Expand" : "Collapse"}
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(text);
                setCopied(true);
                setTimeout(() => setCopied(false), 1200);
              } catch {
                /* ignore */
              }
            }}
            aria-label="Copy"
          >
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          </Button>
        </div>
      </div>
      {!collapsed && (
        <pre
          className="overflow-auto p-3 text-[12px] leading-relaxed scrollbar-thin"
          style={maxHeight ? { maxHeight } : undefined}
        >
          <code>{text}</code>
        </pre>
      )}
    </div>
  );
}

function safeStringify(v: unknown) {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}
