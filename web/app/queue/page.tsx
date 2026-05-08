"use client";

import * as React from "react";
import { Filter, RefreshCcw, Search } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { QueueLane } from "@/components/queue/QueueLane";
import { LANE_META, LANE_ORDER, sortItemsForLane } from "@/components/queue/laneMeta";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { useApprovals } from "@/lib/api";
import type { ApprovalItem } from "@/lib/schemas";
import { useQueryClient } from "@tanstack/react-query";

type AgeBucket = { value: string; label: string; ms?: number; invert?: boolean };
const AGE_BUCKETS: AgeBucket[] = [
  { value: "any", label: "Any age" },
  { value: "1h", label: "< 1h", ms: 3_600_000 },
  { value: "24h", label: "< 24h", ms: 86_400_000 },
  { value: "stale", label: "> 24h", ms: 86_400_000, invert: true },
];

export default function QueuePage() {
  const { data, isLoading } = useApprovals();
  const qc = useQueryClient();
  const [search, setSearch] = React.useState("");
  const [agentFilter, setAgentFilter] = React.useState<string>("all");
  const [workflowFilter, setWorkflowFilter] = React.useState<string>("all");
  const [ageFilter, setAgeFilter] = React.useState<string>("any");

  const items = data ?? [];
  const agents = Array.from(new Set(items.map((i) => i.agent_id))).sort();
  const workflows = Array.from(new Set(items.map((i) => i.workflow))).sort();

  const filtered = React.useMemo<ApprovalItem[]>(() => {
    const q = search.trim().toLowerCase();
    return items.filter((i) => {
      if (agentFilter !== "all" && i.agent_id !== agentFilter) return false;
      if (workflowFilter !== "all" && i.workflow !== workflowFilter) return false;
      const bucket = AGE_BUCKETS.find((b) => b.value === ageFilter);
      if (bucket?.ms) {
        const age = Date.now() - +new Date(i.created_at);
        if (bucket.invert ? age <= bucket.ms : age > bucket.ms) return false;
      }
      if (q) {
        const blob = `${i.agent_id} ${i.workflow} ${i.summary ?? ""} ${i.rationale ?? ""} ${i.approval_id}`.toLowerCase();
        if (!blob.includes(q)) return false;
      }
      return true;
    });
  }, [items, agentFilter, workflowFilter, ageFilter, search]);

  return (
    <AppShell search={search} onSearchChange={setSearch}>
      <div className="container mx-auto flex max-w-[1600px] flex-col gap-3 px-3 py-4 md:px-6">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="mr-2 text-lg font-semibold tracking-tight">Approval Queue</h1>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <div className="relative md:hidden">
              <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search…"
                className="h-9 w-44 pl-8"
              />
            </div>
            <Filter className="hidden h-4 w-4 text-muted-foreground md:inline" />
            <Select value={agentFilter} onValueChange={setAgentFilter}>
              <SelectTrigger className="h-9 w-[160px]">
                <SelectValue placeholder="Agent" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All agents</SelectItem>
                {agents.map((a) => (
                  <SelectItem key={a} value={a}>
                    {a}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={workflowFilter} onValueChange={setWorkflowFilter}>
              <SelectTrigger className="h-9 w-[180px]">
                <SelectValue placeholder="Workflow" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All workflows</SelectItem>
                {workflows.map((w) => (
                  <SelectItem key={w} value={w}>
                    {w}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={ageFilter} onValueChange={setAgeFilter}>
              <SelectTrigger className="h-9 w-[120px]">
                <SelectValue placeholder="Age" />
              </SelectTrigger>
              <SelectContent>
                {AGE_BUCKETS.map((b) => (
                  <SelectItem key={b.value} value={b.value}>
                    {b.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              size="icon"
              onClick={() => qc.invalidateQueries({ queryKey: ["approvals"] })}
              aria-label="Refresh"
            >
              <RefreshCcw className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {isLoading ? (
          <div className="grid gap-3 lg:grid-cols-3">
            {LANE_ORDER.map((l) => (
              <Skeleton key={l} className="h-[60vh] w-full" />
            ))}
          </div>
        ) : (
          <>
            {/* Desktop: 3 lanes side by side */}
            <div className="hidden gap-3 lg:grid lg:grid-cols-3">
              {LANE_ORDER.map((lane) => (
                <QueueLane
                  key={lane}
                  lane={lane}
                  items={sortItemsForLane(filtered, lane)}
                  className="h-[calc(100vh-12rem)]"
                />
              ))}
            </div>
            {/* Mobile/tablet: tabs */}
            <div className="lg:hidden">
              <Tabs defaultValue={LANE_ORDER[0]} className="w-full">
                <TabsList className="w-full">
                  {LANE_ORDER.map((lane) => (
                    <TabsTrigger key={lane} value={lane} className="flex-1 text-xs">
                      {LANE_META[lane].short}
                      <span className="ml-1.5 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">
                        {sortItemsForLane(filtered, lane).length}
                      </span>
                    </TabsTrigger>
                  ))}
                </TabsList>
                {LANE_ORDER.map((lane) => (
                  <TabsContent key={lane} value={lane}>
                    <QueueLane
                      lane={lane}
                      items={sortItemsForLane(filtered, lane)}
                      className="h-[calc(100vh-14rem)]"
                    />
                  </TabsContent>
                ))}
              </Tabs>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
