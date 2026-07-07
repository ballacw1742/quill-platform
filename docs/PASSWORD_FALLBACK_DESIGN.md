# Password fallback for approval action-assertions — design note

Sprint: approvals-password-fallback (2026-07-07). Context: Quill moved from
`quill-web-qdur2ylusq-uc.a.run.app` to `quillpm.com`. WebAuthn RP is now
`quillpm.com`, so every passkey registered under the old run.app RP is
orphaned — the browser will refuse to use it on the new domain and users must
re-register. Until they do (and for any user without a passkey), approvals
were hard-blocked: `POST /v1/auth/passkey/challenge/begin` 412s with zero
usable passkeys and the ceremony NotAllowedErrors with orphaned ones.

## Contract

### New endpoint

`POST /v1/auth/password/challenge` → `ActionAssertionOut` (identical shape to
`/v1/auth/passkey/challenge/complete`):

```json
// request  (Authorization: Bearer <jwt> REQUIRED)
{ "password": "…", "action_intent": { "approval_id": "…", "decision": "approve", "edits": null, "rejection_reason": null, "escalate_to_lane": null } }
// response 200
{ "auth_assertion": "<jwt>", "expires_in": 60 }
```

The body mirrors what the passkey path binds: the passkey challenge stores
`action_intent` at `/begin` and re-checks it at `/complete`; the password path
binds the same `ActionIntent` schema directly (no ceremony needed — there is
no challenge/response round trip to protect).

Errors:

- `401` — wrong password (same detail style as login: `invalid password`).
- `400` — account has no `password_hash` (Google-SSO-only users): clear
  message telling them to register a passkey.
- `403` — caller is not owner/partner (same `_check_lane_authority` pre-check
  as the passkey path).
- `429` — `AUTH_LIMIT` (10/min per IP), same limiter class as login, so the
  endpoint is no better a brute-force oracle than `/v1/auth/login`.

### Token compatibility

The minted token is the SAME action-assertion JWT
(`mint_action_assertion_jwt`): same secret, scope `approval-decision`, same
`sub/role/intent_hash/intent/jti/exp` claims, 60 s TTL, one-shot jti. Two
additive claims:

- `method`: `"password"` (passkey path now stamps `"passkey"` explicitly;
  older tokens without the claim are treated as passkey).
- `cred`: sentinel string `"password"` instead of a credential id.

`verify_action_assertion_jwt` is unchanged — it never inspects `method`/`cred`
— so `/v1/approvals/{id}/decide` accepts the token identically. The ONLY
change in `approvals.decide` is audit fidelity: when the verified claims say
`method == "password"`, the decision record's `auth_method` is
`AuthMethod.PASSWORD` instead of `PASSKEY`. (The `AuthMethod` enum already
had `password`; no schema/migration needed — `auth_method` is an existing
column on decision records.)

### Security invariants

1. Two proofs from the same user: a live bearer session (JWT) AND the
   account password. Session alone can't approve; password alone can't
   authenticate.
2. Intent-bound: token only works for the exact decision
   (`intent_hash`), single-use (`jti`), 60 s expiry — identical replay
   posture to the passkey token.
3. Rate-limited at `AUTH_LIMIT` per IP.
4. Audited: decision records show `auth_method = "password"` so a
   passkey-signed approval is distinguishable from a password-confirmed one
   forever.
5. Role pre-check mirrors the passkey path (owner/partner only); final
   authority enforcement stays in `services.approvals.decide_approval`.

## Web

- `lib/auth.ts` gains `challengePassword(actionIntent, password)` and
  `shouldOfferPasswordFallback(err)`. Fallback classification: offer the
  password path for WebAuthn ceremony failures (`NotAllowedError`,
  `InvalidStateError`, `AbortError`/timeout, unsupported browser) and for
  `412` from `challenge/begin` (zero usable passkeys). Do NOT auto-offer for
  session-level `401`/`403` — a dead session or missing role fails the
  password path too.
- `BiometricPrompt` (mobile overlay) and `PasskeyChallengeModal` (desktop
  dialog): on a fallback-eligible failure the UI switches to a password
  confirmation form automatically; a manual "Use password instead" escape
  hatch is always visible. The old `NEXT_PUBLIC_DEV_AUTH_FALLBACK` opaque-
  token hack in `BiometricPrompt` is replaced by the real endpoint (the dev
  env flag no longer gates the button; the server decides who may use it).
- `/profile/passkeys`: banner explaining the quillpm.com domain move —
  passkeys registered before the move won't work and must be re-added.
  (We cannot tell server-side which stored credentials belong to the old RP —
  rp_id isn't stored — so the banner shows whenever the page renders, and the
  approve-flow 412/failure path carries the same hint.)

## Out of scope / caveats

- Old-RP credentials remain listed in `/profile/passkeys` and can't be
  distinguished from new ones server-side (visible-tolerable); users can
  revoke them manually.
- dev-chat's `_check_passkey` uses a different intent shape and continues to
  rely on `DEV_AUTH_FALLBACK` opaque tokens — unchanged by this sprint.
