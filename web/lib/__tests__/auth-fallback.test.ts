/**
 * Password re-auth fallback — web side (Sprint approvals-password-fallback).
 *
 * The passkey ceremony is the primary approval re-auth, but the quillpm.com
 * domain move orphaned old-RP passkeys. These tests cover the two pure pieces
 * of the fallback that live in lib/auth.ts (the DOM-rendering pieces live in
 * the components, which this repo's vitest setup — node env, no jsdom — can't
 * mount):
 *
 *   1. shouldOfferPasswordFallback(err): the classifier that decides whether a
 *      passkey failure should switch the UI to the password form.
 *   2. challengePassword(intent, pw): calls POST /v1/auth/password/challenge
 *      with the correct payload and returns the minted action-assertion.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AuthError,
  challengePassword,
  shouldOfferPasswordFallback,
  type ActionIntent,
} from "@/lib/auth";

function domError(name: string, message = ""): Error {
  const e = new Error(message || name);
  e.name = name;
  return e;
}

const INTENT: ActionIntent = {
  approval_id: "APR-1",
  decision: "approve",
  edits: null,
  rejection_reason: null,
  escalate_to_lane: null,
};

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// shouldOfferPasswordFallback — the fallback trigger
// ---------------------------------------------------------------------------
describe("shouldOfferPasswordFallback", () => {
  it("offers fallback for WebAuthn ceremony failures", () => {
    for (const name of [
      "NotAllowedError",
      "InvalidStateError",
      "AbortError",
      "NotSupportedError",
      "SecurityError",
    ]) {
      expect(shouldOfferPasswordFallback(domError(name))).toBe(true);
    }
  });

  it("offers fallback on timeout / unsupported messages", () => {
    expect(shouldOfferPasswordFallback(new Error("ceremony timed out"))).toBe(
      true,
    );
    expect(
      shouldOfferPasswordFallback(new Error("WebAuthn not supported here")),
    ).toBe(true);
  });

  it("offers fallback for a 412 from challenge/begin (no usable passkeys)", () => {
    expect(
      shouldOfferPasswordFallback(new AuthError(412, "no registered passkeys")),
    ).toBe(true);
  });

  it("does NOT offer fallback for session/authority errors (401/403)", () => {
    // A dead session or missing role fails the password path too — offering it
    // would just be a second dead end.
    expect(shouldOfferPasswordFallback(new AuthError(401, "unauthorized"))).toBe(
      false,
    );
    expect(shouldOfferPasswordFallback(new AuthError(403, "forbidden"))).toBe(
      false,
    );
  });
});

// ---------------------------------------------------------------------------
// challengePassword — the endpoint call
// ---------------------------------------------------------------------------
describe("challengePassword", () => {
  it("POSTs password + action_intent and returns the assertion", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ auth_assertion: "a.b.c", expires_in: 60 }),
      text: async () => "",
    }));
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    const out = await challengePassword(INTENT, "hunter2");

    expect(out).toEqual({ auth_assertion: "a.b.c", expires_in: 60 });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toContain("/api/v1/auth/password/challenge");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ password: "hunter2", action_intent: INTENT });
  });

  it("throws an AuthError carrying the server status (e.g. 401 wrong pw)", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 401,
      json: async () => ({ detail: "invalid password" }),
      text: async () => "invalid password",
    }));
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    await expect(challengePassword(INTENT, "wrong")).rejects.toMatchObject({
      status: 401,
    });
  });

  it("surfaces the 400 no-password-hash status for the SSO-only nudge", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 400,
      json: async () => ({ detail: "account has no password set" }),
      text: async () => "account has no password set",
    }));
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    await expect(challengePassword(INTENT, "x")).rejects.toMatchObject({
      status: 400,
    });
  });
});
