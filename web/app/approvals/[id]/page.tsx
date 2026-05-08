"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, History } from "lucide-react";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import { ProposedActionPane } from "@/components/approval/ProposedActionPane";
import { ContextPane } from "@/components/approval/ContextPane";
import { DecisionPane } from "@/components/approval/DecisionPane";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useApproval, useAudit } from "@/lib/api";
import { LANE_META } from "@/components/queue/laneMeta";
import { shortHash } from "@/lib/utils";

export default function ApprovalDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { data: item, isLoading, isError } = useApproval(id);
  const { data: audit = [] } = useAudit();
  const trail = audit.filter((e) => e.approval_id === id).sort((a, b) => a.seq - b.seq);

  return (
    <AppShell>
      <div className="container mx-auto flex max-w-[1600px] flex-col gap-3 px-3 py-4 md:px-6">
        <div className="flex items-center gap-2">
          <Button asChild variant="ghost" size="sm">
            <Link href="/queue">
              <ArrowLeft className="h-4 w-4" /> Queue
            </Link>
          </Button>
          {item && (
            <>
              <Badge variant="outline" className="font-mono text-[10px]">
                {item.approval_id}
              </Badge>
              <Badge variant="secondary" className={LANE_META[item.lane].tone}>
                {LANE_META[item.lane].short}
              </Badge>
              <Badge variant="muted" className="capitalize">
                {item.status}
              </Badge>
            </>
          )}
        </div>

        {isLoading && (
          <div className="grid gap-3 lg:grid-cols-3">
            <Skeleton className="h-[60vh]" />
            <Skeleton className="h-[60vh]" />
            <Skeleton className="h-[60vh]" />
          </div>
        )}
        {isError && (
          <Card className="p-6 text-sm text-destructive">Failed to load approval.</Card>
        )}
        {!isLoading && !item && !isError && (
          <Card className="p-6 text-sm text-muted-foreground">Not found.</Card>
        )}

        {item && (
          <>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-3 lg:[&>*]:max-h-[calc(100vh-14rem)]">
              <ProposedActionPane item={item} />
              <ContextPane item={item} />
              <DecisionPane item={item} />
            </div>

            <Card className="mt-2 p-3">
              <Accordion type="single" collapsible defaultValue="trail">
                <AccordionItem value="trail" className="border-0">
                  <AccordionTrigger>
                    <span className="flex items-center gap-2">
                      <History className="h-4 w-4" /> Audit trail
                      <Badge variant="muted" className="ml-1">
                        {trail.length}
                      </Badge>
                    </span>
                  </AccordionTrigger>
                  <AccordionContent>
                    {trail.length === 0 ? (
                      <div className="text-xs text-muted-foreground">No entries yet.</div>
                    ) : (
                      <ol className="space-y-2 border-l pl-4">
                        {trail.map((e) => (
                          <li key={e.seq} className="relative">
                            <span className="absolute -left-[19px] top-1.5 inline-block h-2.5 w-2.5 rounded-full border bg-background" />
                            <div className="flex flex-wrap items-center gap-2 text-xs">
                              <Badge variant="outline" className="font-mono text-[10px]">
                                #{e.seq}
                              </Badge>
                              <span className="font-mono text-muted-foreground">{e.action}</span>
                              <span className="text-muted-foreground">·</span>
                              <span>{e.actor}</span>
                              <span className="text-muted-foreground">·</span>
                              <span className="text-muted-foreground">
                                {new Date(e.ts).toLocaleString()}
                              </span>
                              <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                                {shortHash(e.hash)}
                              </span>
                            </div>
                            {e.notes && (
                              <div className="mt-0.5 text-xs text-muted-foreground">{e.notes}</div>
                            )}
                          </li>
                        ))}
                      </ol>
                    )}
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            </Card>
          </>
        )}
      </div>
    </AppShell>
  );
}
