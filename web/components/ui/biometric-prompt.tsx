"use client";

import * as React from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import { AlertTriangle, Fingerprint, KeyRound, Loader2 } from "lucide-react";
import {
  challengePasskey,
  challengePassword,
  isPasskeySupported,
  isUserCancelledError,
  shouldOfferPasswordFallback,
  type ActionAssertion,
  type ActionIntent,
} from "@/lib/auth";
import { useSession } from "@/lib/api";
import type { Session } from "@/lib/schemas";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";


/**
 * Full-screen biometric / passkey ceremony overlay.
 *
 * Replaces the previous Radix-Dialog-based PasskeyChallengeModal styling per
 * MOBILE_UX_SPEC §"Cross-cutting flows / Passkey ceremony":
 *
 * - Covers the entire viewport including the tab bar (z-50, fixed inset-0).
 * - Centered: large Fingerprint glyph, title (text-title-2), subtitle (text-body),
 *   countdown (text-footnote, label-secondary), "Use passkey" primary button,
 *   Cancel ghost button.
 * - The actual biometric UI is the OS prompt (Face ID / Touch ID); our screen
 *   is just the framing.
 *
 * Lifecycle:
 *   1. open=true and actionIntent provided → fire WebAuthn assertion immediately
 *      via challengePasskey() (no extra "tap to confirm" — the OS prompt IS the
 *      confirmation).
 *   2. On success → onConfirm(assertion); we close.
 *   3. On user cancel → set error string, allow retry.
 *   4. Countdown ticks down from 60 s; on expiry, show error.
 */
export function BiometricPrompt({
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
  actionIntent?: ActionIntent;
  onConfirm: (assertion?: ActionAssertion) => void | Promise<void>;
  destructive?: boolean;
}) {
  const reduceMotion = useReducedMotion();
  const supported = isPasskeySupported();
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = React.useState(60);

  // Password fallback state. Always available (the server decides who may use
  // it): the quillpm.com domain move orphaned old passkeys, so password
  // re-auth is the recovery path when the ceremony fails or nothing signs.
  const [showPasswordForm, setShowPasswordForm] = React.useState(false);
  const [password, setPassword] = React.useState("");
  const { data: rawSession } = useSession();
  const session = rawSession as Session | null | undefined;

  // Reset on each open
  React.useEffect(() => {
    if (open) {
      setError(null);
      setSecondsLeft(60);
      setShowPasswordForm(false);
      setPassword("");
    }
  }, [open]);

  // Countdown timer
  React.useEffect(() => {
    if (!open) return;
    const t = setInterval(() => {
      setSecondsLeft((s) => Math.max(0, s - 1));
    }, 1000);
    return () => clearInterval(t);
  }, [open]);

  React.useEffect(() => {
    if (open && secondsLeft === 0) {
      setError("Challenge expired. Try again.");
    }
  }, [open, secondsLeft]);

  const runChallenge = React.useCallback(async () => {
    if (actionIntent && !supported) {
      setError("Passkeys aren't supported in this browser.");
      return;
    }
    if (secondsLeft === 0) {
      setSecondsLeft(60);
      setError(null);
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
      // A fallback-eligible failure (ceremony broke / no usable passkey / 412)
      // auto-switches to the password form so the approver isn't dead-ended
      // after the quillpm.com passkey orphaning. Plain user-cancel just offers
      // a retry (they may want to try the passkey again).
      if (shouldOfferPasswordFallback(err) && !isUserCancelledError(err)) {
        setShowPasswordForm(true);
        setError("Passkey unavailable. Confirm with your password instead.");
      } else if (isUserCancelledError(err)) {
        setError("Cancelled. Try again to confirm.");
      } else {
        // eslint-disable-next-line no-console
        console.error("biometric confirm failed", err);
        setError("Your passkey wasn't recognized. Try again.");
      }
    } finally {
      setPending(false);
    }
  }, [actionIntent, supported, secondsLeft, onConfirm, onOpenChange]);

  // Auto-fire on open (matches iOS behaviour where biometric prompts fire
  // immediately on user action, not on a follow-up button tap).
  // NB: skip auto-fire if the user has switched to the password form.
  const autoFiredFor = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!open || !actionIntent || !supported || showPasswordForm) return;
    const key = `${actionIntent.approval_id}:${actionIntent.decision}`;
    if (autoFiredFor.current === key) return;
    autoFiredFor.current = key;
    void runChallenge();
  }, [open, actionIntent, supported, runChallenge, showPasswordForm]);

  // Password re-auth fallback. Calls the real POST /v1/auth/password/challenge
  // endpoint, which mints the SAME action-assertion JWT the passkey path
  // returns (method="password"); /decide accepts it identically. Requires an
  // authenticated session AND the correct password (two proofs). The server
  // decides eligibility (401 wrong pw, 400 no password_hash, 403 wrong role),
  // so there is no client-side dev gate anymore.
  const runPasswordChallenge = React.useCallback(async () => {
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
      // Surface the server's message where useful (wrong password, no password
      // set, wrong role) instead of a generic string.
      let msg = "Couldn't verify password. Check it and try again.";
      const anyErr = err as { status?: number; message?: string };
      if (anyErr?.status === 400) {
        msg =
          "This account has no password set. Register a passkey to approve.";
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
  }, [actionIntent, password, onConfirm, onOpenChange]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-label={title}
          className="fixed inset-0 z-[60] flex flex-col bg-bg pt-safe pb-safe"
          initial={reduceMotion ? { opacity: 1 } : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: reduceMotion ? 0 : 0.24, ease: [0.32, 0.72, 0, 1] }}
        >
          {/* Top bar with Cancel */}
          <div className="flex items-center px-4 pt-3 pb-2">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              disabled={pending}
              className="text-body text-accent active:opacity-60 no-tap-highlight min-h-[44px] -ml-2 px-2"
            >
              Cancel
            </button>
            <span className="ml-auto text-footnote text-label-secondary tabular-nums">
              Expires in {secondsLeft}s
            </span>
          </div>

          {/* Hero */}
          <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
            <div
              className={cn(
                "mb-6 flex h-24 w-24 items-center justify-center rounded-full",
                destructive
                  ? "bg-danger/10 text-danger"
                  : "bg-accent/10 text-accent",
              )}
              aria-hidden="true"
            >
              {pending ? (
                <Loader2 className="h-12 w-12 animate-spin" />
              ) : (
                <Fingerprint className="h-12 w-12" strokeWidth={1.75} />
              )}
            </div>
            <h2 className="text-title-2 text-label-primary">{title}</h2>
            <p className="mt-2 max-w-sm text-body text-label-secondary">
              {description}
            </p>

            {!supported && actionIntent && (
              <div className="mt-4 flex items-center gap-2 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-callout text-danger">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span>Passkeys aren’t supported in this browser.</span>
              </div>
            )}

            {error && (
              <div className="mt-4 flex items-center gap-2 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-callout text-danger">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}
          </div>

          {/* Password fallback form (shown when user taps "Use password instead"
              or after a fallback-eligible passkey failure). */}
          {showPasswordForm && (
            <div className="px-6 pb-2">
              <label
                htmlFor="approval-password"
                className="mb-1 block text-subhead text-label-secondary text-left"
              >
                Password for {session?.email ?? "current account"}
              </label>
              <Input
                id="approval-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                className="h-[50px] rounded-lg border-separator-opaque bg-bg-tertiary text-body"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !pending && password) {
                    void runPasswordChallenge();
                  }
                }}
              />
            </div>
          )}

          {/* Bottom action stack */}
          <div className="px-4 pb-4 pt-3 space-y-2">
            {showPasswordForm ? (
              <>
                <Button
                  type="button"
                  onClick={runPasswordChallenge}
                  disabled={pending || !password}
                  variant={destructive ? "destructive" : "default"}
                  className="w-full h-[50px] text-headline rounded-lg"
                >
                  {pending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" /> Verifying…
                    </>
                  ) : (
                    <>
                      <KeyRound className="h-4 w-4" /> Confirm with password
                    </>
                  )}
                </Button>
                <button
                  type="button"
                  onClick={() => {
                    setShowPasswordForm(false);
                    setPassword("");
                    setError(null);
                  }}
                  className="block w-full py-3 text-center text-callout text-accent active:opacity-60 no-tap-highlight"
                >
                  Use passkey instead
                </button>
              </>
            ) : (
              <>
                <Button
                  type="button"
                  onClick={runChallenge}
                  disabled={pending || (!!actionIntent && !supported)}
                  variant={destructive ? "destructive" : "default"}
                  className="w-full h-[50px] text-headline rounded-lg"
                >
                  {pending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" /> Awaiting biometric…
                    </>
                  ) : (
                    <>
                      <Fingerprint className="h-4 w-4" /> Use passkey
                    </>
                  )}
                </Button>
                <button
                  type="button"
                  onClick={() => {
                    setShowPasswordForm(true);
                    setError(null);
                  }}
                  className="block w-full py-3 text-center text-callout text-accent active:opacity-60 no-tap-highlight"
                >
                  Use password instead
                </button>
              </>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
