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

class AuthError extends Error {
  constructor(public status: number, msg: string) {
    super(msg);
  }
}

async function jpost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
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
// Credential management
// ---------------------------------------------------------------------------
export async function listPasskeys(): Promise<PasskeyCredential[]> {
  return jget<PasskeyCredential[]>("/api/v1/auth/passkey/credentials");
}

export async function revokePasskey(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/auth/passkey/credentials/${id}`, {
    method: "DELETE",
    credentials: "include",
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
