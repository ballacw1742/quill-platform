"use client";

import * as React from "react";
import { CheckCircle2, Fingerprint, KeyRound, Loader2, ShieldCheck } from "lucide-react";
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
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  isPasskeySupported,
  isUserCancelledError,
  registerPasskey,
} from "@/lib/auth";
import { toast } from "sonner";

type Step = "intro" | "naming" | "prompting" | "success";

export function RegisterPasskeyDialog({
  open,
  onOpenChange,
  onRegistered,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onRegistered?: () => void;
}) {
  const [step, setStep] = React.useState<Step>("intro");
  const [name, setName] = React.useState("");
  const [attachment, setAttachment] = React.useState<
    "platform" | "cross-platform"
  >("platform");
  const [error, setError] = React.useState<string | null>(null);
  const supported = isPasskeySupported();

  React.useEffect(() => {
    if (!open) {
      // Reset on close so the next open is fresh.
      setTimeout(() => {
        setStep("intro");
        setName("");
        setAttachment("platform");
        setError(null);
      }, 200);
    }
  }, [open]);

  const begin = (kind: "platform" | "cross-platform") => {
    setAttachment(kind);
    setName(kind === "platform" ? "This device" : "Hardware key");
    setStep("naming");
  };

  const submit = async () => {
    setError(null);
    setStep("prompting");
    try {
      await registerPasskey({ attachment, name: name.trim() || undefined });
      setStep("success");
      toast.success("Passkey registered");
      onRegistered?.();
    } catch (err) {
      if (isUserCancelledError(err)) {
        setError("Registration cancelled.");
      } else {
        setError(err instanceof Error ? err.message : "Registration failed");
      }
      setStep("naming");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" /> Register a passkey
          </DialogTitle>
          <DialogDescription>
            Replace passwords with biometric (Touch ID / Face ID / iCloud
            Keychain) or a hardware security key.
          </DialogDescription>
        </DialogHeader>

        {!supported && (
          <Alert variant="destructive">
            <AlertDescription>
              Your browser doesn’t support WebAuthn. Use Safari, Chrome, Edge,
              or Firefox on a modern device.
            </AlertDescription>
          </Alert>
        )}

        {supported && step === "intro" && (
          <div className="grid gap-3">
            <button
              onClick={() => begin("platform")}
              className="flex items-start gap-3 rounded-md border p-4 text-left hover:bg-muted/40"
            >
              <Fingerprint className="mt-0.5 h-6 w-6 text-primary" />
              <div>
                <div className="font-medium">This device</div>
                <div className="text-xs text-muted-foreground">
                  Use Touch ID, Face ID, or your platform PIN. Syncs to other
                  Apple devices via iCloud Keychain.
                </div>
              </div>
            </button>
            <button
              onClick={() => begin("cross-platform")}
              className="flex items-start gap-3 rounded-md border p-4 text-left hover:bg-muted/40"
            >
              <KeyRound className="mt-0.5 h-6 w-6 text-primary" />
              <div>
                <div className="font-medium">Hardware security key</div>
                <div className="text-xs text-muted-foreground">
                  YubiKey, Titan, or any FIDO2 device.
                </div>
              </div>
            </button>
          </div>
        )}

        {supported && step === "naming" && (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="passkey-name">Name this passkey</Label>
              <Input
                id="passkey-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={
                  attachment === "platform" ? "Charles’ Mac" : "YubiKey 5C"
                }
                autoFocus
              />
            </div>
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
          </div>
        )}

        {supported && step === "prompting" && (
          <div className="flex items-center justify-center gap-3 rounded-md border bg-muted/40 p-6 text-sm">
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
            Waiting for{" "}
            {attachment === "platform"
              ? "Touch ID / Face ID"
              : "your security key"}
            …
          </div>
        )}

        {supported && step === "success" && (
          <div className="flex items-center gap-3 rounded-md border bg-muted/40 p-4 text-sm">
            <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            Passkey registered. You can sign in with it next time.
          </div>
        )}

        <DialogFooter>
          {step === "naming" && (
            <>
              <Button variant="ghost" onClick={() => setStep("intro")}>
                Back
              </Button>
              <Button onClick={submit}>
                <Fingerprint className="h-4 w-4" /> Register
              </Button>
            </>
          )}
          {step === "intro" && (
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
          )}
          {step === "success" && (
            <Button onClick={() => onOpenChange(false)}>Done</Button>
          )}
          {step === "prompting" && (
            <Button variant="ghost" disabled>
              Working…
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
