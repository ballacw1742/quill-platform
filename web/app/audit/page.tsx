"use client";

import * as React from "react";
import Link from "next/link";
import { CloudOff, Database, RefreshCw, Search, ShieldCheck, ShieldAlert } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { HashChainVerifier } from "@/components/audit/HashChainVerifier";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useAudit,
  useAuditMirrorStatus,
  useRecentAuditVerifications,
  useTriggerAuditVerify,
} from "@/lib/api";
import { shortHash } from "@/lib/utils";

function formatLag(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(0)}s behind`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)} min behind`;
  return `${(seconds / 3600).toFixed(1)} h behind`;
}

function OffsiteMirrorCard() {
  const { data: status, isLoading } = useAuditMirrorStatus();
  const { data: verifications } = useRecentAuditVerifications(5);
  const trigger = useTriggerAuditVerify();

  if (isLoading || !status) {
    return <Skeleton className="h-28 w-full" />;
  }

  const lastVerify = verifications?.[0];
  const verifyOk = lastVerify?.result === "ok";
  const isLocal = status.mode === "local";
  const queueWarn = status.queue_depth > 5;
  const lagWarn = (status.lag_seconds ?? 0) > 15 * 60;

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 p-3 md:p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            {isLocal ? (
              <Database className="h-4 w-4 text-amber-500" aria-label="local mode" />
            ) : (
              <CloudOff className="h-4 w-4 text-emerald-600" aria-label="b2 mode" />
            )}
            <span className="text-sm font-medium">Offsite mirror</span>
            <Badge variant={isLocal ? "secondary" : "default"} className="text-[10px]">
              {isLocal ? "local-disk dev mode" : `b2://${status.bucket ?? "quill-audit"}`}
            </Badge>
          </div>
          <div className="text-xs text-muted-foreground">
            <span className={lagWarn ? "text-destructive font-medium" : ""}>
              {formatLag(status.lag_seconds)}
            </span>
            {" • "}
            <span className={queueWarn ? "text-destructive font-medium" : ""}>
              queue depth {status.queue_depth}
            </span>
            {" • "}
            mirrored {status.total_mirrored.toLocaleString()}
            {status.total_failed > 0 && (
              <span className="text-destructive">
                {" • "}failed {status.total_failed}
              </span>
            )}
          </div>
          <div className="ml-auto flex items-center gap-2">
            {lastVerify ? (
              <Badge
                variant={verifyOk ? "secondary" : "destructive"}
                className="flex items-center gap-1 text-[10px]"
              >
                {verifyOk ? (
                  <ShieldCheck className="h-3 w-3" />
                ) : (
                  <ShieldAlert className="h-3 w-3" />
                )}
                last verify: {lastVerify.result}
              </Badge>
            ) : null}
            <Button
              size="sm"
              variant="outline"
              onClick={() => trigger.mutate()}
              disabled={trigger.isPending}
            >
              <RefreshCw className={`mr-1 h-3.5 w-3.5 ${trigger.isPending ? "animate-spin" : ""}`} />
              Verify now
            </Button>
          </div>
        </div>
        <div className="text-[11px] text-muted-foreground">
          {status.last_mirrored_at
            ? `Last successful mirror: ${new Date(status.last_mirrored_at).toLocaleString()} (seq ${status.last_mirrored_seq ?? "—"})`
            : "No mirror writes yet this process."}
          {status.last_error ? (
            <span className="ml-2 text-destructive">last error: {status.last_error}</span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

export default function AuditPage() {
  const { data, isLoading } = useAudit();
  const [q, setQ] = React.useState("");
  const [actionFilter, setActionFilter] = React.useState("all");

  const entries = data ?? [];
  const actions = Array.from(new Set(entries.map((e) => e.action))).sort();

  const filtered = entries.filter((e) => {
    if (actionFilter !== "all" && e.action !== actionFilter) return false;
    if (!q.trim()) return true;
    const blob = `${e.action} ${e.actor} ${e.approval_id ?? ""} ${e.agent_id ?? ""} ${e.notes ?? ""} ${e.hash}`.toLowerCase();
    return blob.includes(q.toLowerCase());
  });

  return (
    <AppShell>
      <div className="container mx-auto flex max-w-[1400px] flex-col gap-4 px-3 py-4 md:px-6">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-semibold tracking-tight">Audit log</h1>
          <p className="text-sm text-muted-foreground">
            Hash-chained, append-only. Every approval decision and execution lands here.
          </p>
        </div>

        <HashChainVerifier
          initial={
            entries.length
              ? {
                  ok: true,
                  total: entries.length,
                  verified: entries.length,
                  broken_at: null,
                  checked_at: new Date().toISOString(),
                }
              : undefined
          }
        />

        <OffsiteMirrorCard />

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[12rem] max-w-md">
            <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by actor, hash, approval id…"
              className="pl-8"
            />
          </div>
          <Select value={actionFilter} onValueChange={setActionFilter}>
            <SelectTrigger className="w-[200px]">
              <SelectValue placeholder="Action" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All actions</SelectItem>
              {actions.map((a) => (
                <SelectItem key={a} value={a}>
                  {a}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {isLoading ? (
          <Skeleton className="h-72 w-full" />
        ) : (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">#</TableHead>
                  <TableHead className="w-44">When</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Approval</TableHead>
                  <TableHead className="text-right">Hash</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="py-6 text-center text-muted-foreground">
                      No entries match.
                    </TableCell>
                  </TableRow>
                )}
                {filtered.map((e) => (
                  <TableRow key={e.seq}>
                    <TableCell className="font-mono text-xs">{e.seq}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(e.ts).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="font-mono text-[10px]">
                        {e.action}
                      </Badge>
                      {e.notes && (
                        <div className="mt-0.5 text-[11px] text-muted-foreground">{e.notes}</div>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{e.actor}</TableCell>
                    <TableCell>
                      {e.approval_id ? (
                        <Link
                          href={`/approvals/${e.approval_id}`}
                          className="font-mono text-xs text-primary hover:underline"
                        >
                          {shortHash(e.approval_id, 14)}…
                        </Link>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <span className="font-mono text-[11px] text-muted-foreground" title={e.hash}>
                        {shortHash(e.hash, 12)}…
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </AppShell>
  );
}
