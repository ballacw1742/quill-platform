"use client";

import * as React from "react";
import { Brain, ExternalLink, FileText, Quote } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import type { ApprovalItem } from "@/lib/schemas";

function ConfidenceGauge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const tone = value < 0.7 ? "bg-destructive" : value < 0.85 ? "bg-warning" : "bg-success";
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-muted-foreground">Agent confidence</span>
        <span className={cn("font-mono font-medium", value < 0.7 ? "text-destructive" : value < 0.85 ? "text-warning" : "text-success")}>
          {pct}%
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full transition-all", tone)} style={{ width: `${pct}%` }} />
      </div>
      {value < 0.7 && (
        <div className="text-[11px] text-destructive">
          Below 0.70 threshold — auto-routed to mandatory review.
        </div>
      )}
    </div>
  );
}

export function ContextPane({ item }: { item: ApprovalItem }) {
  return (
    <Card className="flex h-full flex-col">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Brain className="h-4 w-4 text-primary" /> Context
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 space-y-4 overflow-auto">
        <ConfidenceGauge value={item.confidence} />

        <div className="space-y-1">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Project</div>
          <Badge variant="outline" className="font-mono">
            {item.context.project_id}
          </Badge>
        </div>

        <Separator />

        <div className="space-y-2">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Source artifacts ({item.context.sources.length})
          </div>
          <ul className="space-y-2">
            {item.context.sources.map((s, i) => {
              const Icon = FileText;
              const inner = (
                <>
                  <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex items-center gap-2 text-sm">
                      <Badge variant="secondary" className="text-[10px] capitalize">
                        {s.kind.replace("_", " ")}
                      </Badge>
                      <span className="truncate font-mono text-xs">{s.ref}</span>
                      {s.url && <ExternalLink className="h-3 w-3 text-muted-foreground" />}
                    </div>
                    {s.excerpt && (
                      <blockquote className="flex gap-1.5 rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
                        <Quote className="h-3 w-3 shrink-0" />
                        <span className="leading-snug">{s.excerpt}</span>
                      </blockquote>
                    )}
                  </div>
                </>
              );
              return (
                <li key={`${s.kind}-${s.ref}-${i}`}>
                  {s.url ? (
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-start gap-2 rounded-md p-1 transition-colors hover:bg-accent/50"
                    >
                      {inner}
                    </a>
                  ) : (
                    <div className="flex items-start gap-2 p-1">{inner}</div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>

        {item.rationale && (
          <>
            <Separator />
            <div className="space-y-1">
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Agent reasoning
              </div>
              <p className="rounded-md bg-muted/40 p-3 text-sm leading-relaxed">{item.rationale}</p>
            </div>
          </>
        )}

        <Separator />

        <div className="grid grid-cols-2 gap-3 text-[11px]">
          <div>
            <div className="text-muted-foreground">Model</div>
            <div className="font-mono">{item.agent_model ?? "—"}</div>
          </div>
          <div>
            <div className="text-muted-foreground">Prompt version</div>
            <div className="font-mono">{item.prompt_version ?? `${item.agent_id}@${item.agent_version}`}</div>
          </div>
          <div>
            <div className="text-muted-foreground">Created</div>
            <div className="font-mono">{new Date(item.created_at).toLocaleString()}</div>
          </div>
          <div>
            <div className="text-muted-foreground">Expires</div>
            <div className="font-mono">{item.expires_at ? new Date(item.expires_at).toLocaleString() : "—"}</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
