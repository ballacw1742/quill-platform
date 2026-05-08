"use client";

import { ArrowRight, Cloud, Cpu, Wand2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { JsonBlock } from "./JsonBlock";
import type { ApprovalItem } from "@/lib/schemas";

export function ProposedActionPane({ item }: { item: ApprovalItem }) {
  const a = item.proposed_action;
  return (
    <Card className="flex h-full flex-col">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Wand2 className="h-4 w-4 text-primary" /> Proposed action
          </CardTitle>
          <Badge variant="outline" className="font-mono text-[10px]">
            {item.agent_id} @ {item.agent_version}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="flex-1 space-y-4 overflow-auto">
        <div className="space-y-1">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Kind</div>
          <div className="font-mono text-sm">{a.kind}</div>
        </div>

        <div className="space-y-1">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Target</div>
          <div className="flex items-center gap-2 text-sm">
            <Cpu className="h-4 w-4 text-muted-foreground" />
            <span className="font-mono">{a.target_system ?? "draft-only"}</span>
            {a.api_call && (
              <>
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <Badge variant="secondary" className="font-mono text-[10px]">
                  {a.api_call.method}
                </Badge>
                <span className="truncate font-mono text-xs text-muted-foreground">
                  {a.api_call.path}
                </span>
              </>
            )}
          </div>
        </div>

        <Separator />

        <div className="space-y-1">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Payload</div>
          <JsonBlock value={a.payload} maxHeight={360} />
        </div>

        {a.api_call?.body_preview && (
          <div className="space-y-1">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
              API call body preview
            </div>
            <JsonBlock value={a.api_call.body_preview} collapsible defaultCollapsed maxHeight={200} />
          </div>
        )}

        <div className="space-y-1">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Full approval record
          </div>
          <JsonBlock value={item} collapsible defaultCollapsed maxHeight={300} />
        </div>

        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <Cloud className="h-3 w-3" />
          {item.proposed_action.target_system
            ? `If approved, this will be executed against ${item.proposed_action.target_system}.`
            : "Draft-only. No external system will be modified."}
        </div>
      </CardContent>
    </Card>
  );
}
