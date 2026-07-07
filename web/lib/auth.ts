"use client";

import {
  startAuthentication,
  startRegistration,
  browserSupportsWebAuthn,
} from "@simplewebauthn/browser";

// ---------------------------------------------------------------------------
// Wire types — mirror the FastAPI side (api/app/schemas.py).
// ---------------------------------------------------------------------------
export type ActionIntent = {
  approval_id: string;
  decision: "approve" | "edit_then_approve" | "reject" | "escalate";
  edits?: Record<string, unknown> | null;
  rejection_reason?: string | null;
  escalate_to_lane?: number | null;
};

export type PasskeyOptions = {
  ceremony_id: string;
  // Raw PublicKeyCredentialCreationOptions / PublicKeyCredentialRequestOptions JSON
  // as produced by py-webauthn's options_to_json().
  options: any;
};

export type PasskeyCredential = {
  id: string;
  name: string | null;
  transports: string | null;
  attachment: string | null;
  aaguid: string | null;
  backup_eligible: boolean;
  backup_state: boolean;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

const API_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) || "";

export class AuthError extends Error {
  constructor(public status: number, msg: string) {
    super(msg);
    this.name = "AuthError";
  }
}

// Read the Bearer token from localStorage. Mirrors lib/api.ts getStoredToken();
// duplicated here to avoid a circular dependency between lib/auth.ts and lib/api.ts.
function getBearerToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("quill_session_token");
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = getBearerToken();
  return {
    ...(extra ?? {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function jpost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new AuthError(res.status, text || res.statusText);
  }
  return (await res.json()) as T;
}

async function jget<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: authHeaders(),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new AuthError(res.status, text || res.statusText);
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Feature detection
// ---------------------------------------------------------------------------
export function isPasskeySupported(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return browserSupportsWebAuthn();
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Registration ceremony
// ---------------------------------------------------------------------------
export async function registerPasskey(opts: {
  attachment?: "platform" | "cross-platform";
  name?: string;
}): Promise<PasskeyCredential> {
  const begin = await jpost<PasskeyOptions>("/api/v1/auth/passkey/register/begin", {
    attachment: opts.attachment ?? null,
    name: opts.name ?? null,
  });

  // @simplewebauthn/browser handles the base64url ⇄ ArrayBuffer dance.
  const attResp = await startRegistration({ optionsJSON: begin.options });

  return jpost<PasskeyCredential>("/api/v1/auth/passkey/register/complete", {
    ceremony_id: begin.ceremony_id,
    response: attResp,
    name: opts.name ?? null,
  });
}

// ---------------------------------------------------------------------------
// Login ceremony
// ---------------------------------------------------------------------------
export type PasskeyLoginResult = {
  access_token: string;
  user_id: string;
  role: string;
};

export async function loginWithPasskey(email: string): Promise<PasskeyLoginResult> {
  const begin = await jpost<PasskeyOptions>(
    "/api/v1/auth/passkey/login/begin",
    { email },
  );
  const assertion = await startAuthentication({ optionsJSON: begin.options });
  return jpost<PasskeyLoginResult>("/api/v1/auth/passkey/login/complete", {
    ceremony_id: begin.ceremony_id,
    response: assertion,
  });
}

// ---------------------------------------------------------------------------
// Action re-auth ceremony — mints a one-shot JWT bound to action_intent.
// ---------------------------------------------------------------------------
export type ActionAssertion = {
  auth_assertion: string;
  expires_in: number;
};

export async function challengePasskey(
  actionIntent: ActionIntent,
): Promise<ActionAssertion> {
  const begin = await jpost<PasskeyOptions>(
    "/api/v1/auth/passkey/challenge/begin",
    { action_intent: actionIntent },
  );
  const assertion = await startAuthentication({ optionsJSON: begin.options });
  return jpost<ActionAssertion>("/api/v1/auth/passkey/challenge/complete", {
    ceremony_id: begin.ceremony_id,
    response: assertion,
    action_intent: actionIntent,
  });
}

// ---------------------------------------------------------------------------
// Password re-auth fallback (WebAuthn RP moved to quillpm.com; old passkeys
// are orphaned). Mints the SAME action-assertion the passkey path returns,
// with method="password"; /decide accepts it identically.
// ---------------------------------------------------------------------------
export async function challengePassword(
  actionIntent: ActionIntent,
  password: string,
): Promise<ActionAssertion> {
  return jpost<ActionAssertion>("/api/v1/auth/password/challenge", {
    password,
    action_intent: actionIntent,
  });
}

/**
 * Should the UI offer the password fallback for this failure?
 *
 * YES for WebAuthn ceremony failures (the ceremony itself broke or there is
 * nothing to sign) and for a 412 from challenge/begin (zero usable passkeys):
 *  - NotAllowedError  — user dismissed / no matching credential / RP mismatch
 *  - InvalidStateError — credential in an unusable state
 *  - AbortError / timeout — ceremony aborted or timed out
 *  - unsupported browser — no WebAuthn at all
 *  - AuthError status 412 — server says no registered passkeys
 *
 * NO for session-level 401/403 (dead session or missing role) — those fail
 * the password path too, so offering it would just be a second dead end.
 */
export function shouldOfferPasswordFallback(err: unknown): boolean {
  if (err instanceof AuthError) {
    // Only the "no usable passkeys" precondition is fallback-eligible.
    // 401/403 are session/authority failures that password can't fix.
    return err.status === 412;
  }
  if (err instanceof Error) {
    if (
      err.name === "NotAllowedError" ||
      err.name === "InvalidStateError" ||
      err.name === "AbortError" ||
      err.name === "NotSupportedError" ||
      err.name === "SecurityError"
    ) {
      return true;
    }
    if (/timeout|timed out|abort|not supported|unsupported/i.test(err.message)) {
      return true;
    }
  }
  // Unknown/opaque failure (e.g. browser lacks WebAuthn so the ceremony threw
  // a bare Error): offer the fallback rather than dead-ending the approver.
  return !isPasskeySupported();
}

// ---------------------------------------------------------------------------
// Credential management
// ---------------------------------------------------------------------------
export async function listPasskeys(): Promise<PasskeyCredential[]> {
  return jget<PasskeyCredential[]>("/api/v1/auth/passkey/credentials");
}

export async function revokePasskey(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/auth/passkey/credentials/${id}`, {
    method: "DELETE",
    credentials: "include",
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new AuthError(res.status, await res.text());
  }
}

// ---------------------------------------------------------------------------
// Session
// ---------------------------------------------------------------------------
export async function getSession() {
  return jget("/api/v1/auth/me");
}

export async function logout(): Promise<void> {
  // The FastAPI /auth/me path is JWT-bearer based; "logout" is just a client-side
  // token drop for now. Cookie-based sessions land in a future sprint.
  if (typeof window !== "undefined") {
    window.localStorage.removeItem("quill.session");
  }
}

// ---------------------------------------------------------------------------
// Friendly error helpers
// ---------------------------------------------------------------------------
export function isUserCancelledError(e: unknown): boolean {
  if (e instanceof Error) {
    // Standard DOMException name from navigator.credentials.* when the user
    // cancels the prompt.
    return e.name === "NotAllowedError" || /cancel|aborted/i.test(e.message);
  }
  return false;
}
