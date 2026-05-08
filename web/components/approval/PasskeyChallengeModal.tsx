"use client";

import * as React from "react";
import { Fingerprint, Loader2, ShieldCheck, AlertTriangle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  challengePasskey,
  isPasskeySupported,
  isUserCancelledError,
  type ActionAssertion,
  type ActionIntent,
} from "@/lib/auth";

/**
 * PasskeyChallengeModal — Sprint 2.2.
 *
 * On open, immediately fires the WebAuthn challenge (no extra "Confirm" click
 * — the platform's biometric prompt IS the confirmation). Returns the minted
 * `auth_assertion` JWT to the caller via `onConfirm`. The caller threads it
 * into the actual decision request.
 */
export function PasskeyChallengeModal({
  open,
  onOpenChange,
  title,
  description,
  actionIntent,
  onConfirm,
  destructive,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  /**
   * If provided, opens the WebAuthn assertion ceremony bound to this intent
   * and passes the resulting JWT to onConfirm. If omitted, the dialog acts
   * as a soft "confirm" gate (used for admin-side actions that don't yet
   * have a corresponding server-bound intent).
   */
  actionIntent?: ActionIntent;
  onConfirm: (assertion?: ActionAssertion) => void | Promise<void>;
  destructive?: boolean;
}) {
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const supported = isPasskeySupported();

  // Reset error each time the modal opens
  React.useEffect(() => {
    if (open) setError(null);
  }, [open]);

  const handleConfirm = async () => {
    if (actionIntent && !supported) {
      setError("Passkeys aren't supported in this browser.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      let assertion: ActionAssertion | undefined;
      if (actionIntent) {
        assertion = await challengePasskey(actionIntent);
      }
      await onConfirm(assertion);
      onOpenChange(false);
    } catch (err) {
      if (isUserCancelledError(err)) {
        setError("Cancelled. Try again to confirm this action.");
      } else {
        setError(err instanceof Error ? err.message : "Passkey confirmation failed");
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !pending && onOpenChange(v)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" /> {title}
          </DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <div className="rounded-md border bg-muted/40 p-3 text-sm">
          <div className="flex items-center gap-3">
            <Fingerprint className="h-6 w-6 text-primary" />
            <div>
              <div className="font-medium">Confirm with passkey</div>
              {actionIntent ? (
                <div className="text-xs text-muted-foreground">
                  Every approval action requires a fresh passkey check. The
                  signed assertion is bound to{" "}
                  <span className="font-mono">{actionIntent.decision}</span>{" "}
                  on this approval and expires in 60 seconds.
                </div>
              ) : (
                <div className="text-xs text-muted-foreground">
                  Confirm to proceed.
                </div>
              )}
            </div>
          </div>
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={pending}
          >
            Cancel
          </Button>
          <Button
            variant={destructive ? "destructive" : "default"}
            onClick={handleConfirm}
            disabled={pending || (!!actionIntent && !supported)}
          >
            {pending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Fingerprint className="h-4 w-4" />
            )}
            {pending ? "Awaiting biometric…" : "Confirm with passkey"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
