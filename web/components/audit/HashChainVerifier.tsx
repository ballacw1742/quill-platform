"use client";

import * as React from "react";
import { CheckCircle2, Loader2, ShieldAlert, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useVerifyChain } from "@/lib/api";
import type { ChainVerification } from "@/lib/schemas";
import { cn } from "@/lib/utils";

export function HashChainVerifier({ initial }: { initial?: ChainVerification }) {
  const verify = useVerifyChain();
  const result = verify.data ?? initial;

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-3 p-3">
        <div
          className={cn(
            "flex h-9 w-9 items-center justify-center rounded-full",
            result?.ok ? "bg-success/15 text-success" : "bg-destructive/15 text-destructive",
          )}
        >
          {result?.ok ? <ShieldCheck className="h-5 w-5" /> : <ShieldAlert className="h-5 w-5" />}
        </div>
        <div className="min-w-0">
          <div className="text-sm font-medium">
            {result
              ? result.ok
                ? "Audit chain verified"
                : `Chain broken at seq #${result.broken_at ?? "?"}`
              : "Audit chain status unknown"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            {result
              ? `${result.verified}/${result.total} entries · checked ${new Date(result.checked_at).toLocaleString()}`
              : "Run a verification to compute hashes."}
          </div>
        </div>
        {result && (
          <Badge variant={result.ok ? "success" : "destructive"} className="ml-auto">
            {result.ok ? "OK" : "BROKEN"}
          </Badge>
        )}
        <Button onClick={() => verify.mutate()} disabled={verify.isPending} className="ml-auto sm:ml-0">
          {verify.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <CheckCircle2 className="h-4 w-4" />
          )}
          Verify chain
        </Button>
      </CardContent>
    </Card>
  );
}
