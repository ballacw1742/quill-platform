"use client";

import * as React from "react";
import { Fingerprint, Loader2, ShieldCheck } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { challengePasskey } from "@/lib/auth";

export function PasskeyChallengeModal({
  open,
  onOpenChange,
  title,
  description,
  onConfirm,
  destructive,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  onConfirm: (assertion: Awaited<ReturnType<typeof challengePasskey>>) => void | Promise<void>;
  destructive?: boolean;
}) {
  const [pending, setPending] = React.useState(false);

  const handleConfirm = async () => {
    setPending(true);
    try {
      const assertion = await challengePasskey();
      await onConfirm(assertion);
      onOpenChange(false);
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" /> {title}
          </DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-3 rounded-md border bg-muted/40 p-3 text-sm">
          <Fingerprint className="h-6 w-6 text-primary" />
          <div>
            <div className="font-medium">Sprint 1: stub passkey</div>
            <div className="text-xs text-muted-foreground">
              Sprint 2 will trigger your platform authenticator. For now this just confirms intent.
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={pending}>
            Cancel
          </Button>
          <Button
            variant={destructive ? "destructive" : "default"}
            onClick={handleConfirm}
            disabled={pending}
          >
            {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Fingerprint className="h-4 w-4" />}
            Confirm
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
