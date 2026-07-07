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
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  challengePasskey,
  challengePassword,
  isPasskeySupported,
  isUserCancelledError,
  shouldOfferPasswordFallback,
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

  // Password re-auth fallback state. The quillpm.com domain move orphaned old
  // passkeys, so password confirmation is the recovery path when the ceremony
  // fails or there is no usable passkey.
  const [showPasswordForm, setShowPasswordForm] = React.useState(false);
  const [password, setPassword] = React.useState("");

  // Reset each time the modal opens
  React.useEffect(() => {
    if (open) {
      setError(null);
      setShowPasswordForm(false);
      setPassword("");
    }
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
      // Fallback-eligible failure (ceremony broke / no usable passkey / 412)
      // auto-switches to the password form. Plain cancel just offers a retry.
      if (shouldOfferPasswordFallback(err) && !isUserCancelledError(err)) {
        setShowPasswordForm(true);
        setError("Passkey unavailable. Confirm with your password instead.");
      } else if (isUserCancelledError(err)) {
        setError("Cancelled. Try again to confirm this action.");
      } else {
        // eslint-disable-next-line no-console
        console.error("passkey confirmation failed", err);
        setError("Your passkey wasn't recognized. Try again.");
      }
    } finally {
      setPending(false);
    }
  };

  // Password re-auth. Calls POST /v1/auth/password/challenge, which mints the
  // SAME action-assertion JWT the passkey path returns (method="password");
  // /decide accepts it identically. Requires session + correct password.
  const handlePasswordConfirm = async () => {
    if (!actionIntent) {
      setError("Nothing to confirm.");
      return;
    }
    if (!password) {
      setError("Enter your password.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const assertion = await challengePassword(actionIntent, password);
      await onConfirm(assertion);
      onOpenChange(false);
    } catch (err) {
      let msg = "Couldn't verify password. Check it and try again.";
      const anyErr = err as { status?: number };
      if (anyErr?.status === 400) {
        msg = "This account has no password set. Register a passkey to approve.";
      } else if (anyErr?.status === 403) {
        msg = "Your role can't approve this item.";
      } else if (anyErr?.status === 429) {
        msg = "Too many attempts. Wait a minute and try again.";
      }
      // eslint-disable-next-line no-console
      console.error("password fallback failed", err);
      setError(msg);
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

        {showPasswordForm && (
          <div className="space-y-1.5">
            <label
              htmlFor="approval-password-desktop"
              className="text-sm font-medium text-muted-foreground"
            >
              Confirm with your account password
            </label>
            <Input
              id="approval-password-desktop"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !pending && password) {
                  void handlePasswordConfirm();
                }
              }}
            />
          </div>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <DialogFooter className="sm:justify-between">
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={pending}
          >
            Cancel
          </Button>
          {showPasswordForm ? (
            <div className="flex items-center gap-2">
              <Button
                variant="link"
                type="button"
                className="px-2"
                onClick={() => {
                  setShowPasswordForm(false);
                  setPassword("");
                  setError(null);
                }}
                disabled={pending}
              >
                Use passkey instead
              </Button>
              <Button
                variant={destructive ? "destructive" : "default"}
                onClick={handlePasswordConfirm}
                disabled={pending || !password}
              >
                {pending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Fingerprint className="h-4 w-4" />
                )}
                {pending ? "Verifying…" : "Confirm with password"}
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Button
                variant="link"
                type="button"
                className="px-2"
                onClick={() => {
                  setShowPasswordForm(true);
                  setError(null);
                }}
                disabled={pending}
              >
                Use password instead
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
            </div>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
