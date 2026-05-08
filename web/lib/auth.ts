"use client";

// Sprint 1: cookie-session stub. Real session is held server-side; this module
// exposes a thin facade so Sprint 2 can drop in WebAuthn without touching pages.

export type PasskeyAssertion = {
  // Sprint 2 will populate these from navigator.credentials.get(...)
  credentialId?: string;
  clientDataJSON?: string;
  authenticatorData?: string;
  signature?: string;
  // Sprint 1 stub flag
  stub?: true;
};

export async function challengePasskey(): Promise<PasskeyAssertion> {
  // Sprint 1: pretend we asked the platform authenticator and it said yes.
  // The PasskeyChallengeModal handles the user-visible confirm step.
  await new Promise((r) => setTimeout(r, 250));
  return { stub: true };
}

export function isPasskeySupported(): boolean {
  if (typeof window === "undefined") return false;
  return (
    typeof window.PublicKeyCredential === "function" &&
    typeof navigator.credentials?.get === "function"
  );
}
