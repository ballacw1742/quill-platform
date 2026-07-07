# SECRETS.md — per-tenant secrets (KMS envelope encryption) (Sprint B2)

Phase B groundwork for the design doc's "Per-tenant secrets: KMS-encrypted
rows (their bot tokens, their API keys); never in env vars" (§6) and
"Secret Manager + KMS (platform + per-tenant secrets)" (§2). This document
is the canonical contract for how tenant-supplied secrets are stored, read
and rotated. Do not invent fields outside this document — extend it here
first.

**B2 scope:** schema + provider abstraction + `plaintext-dev` backend +
KMS backend implemented against a mocked KMS client. Live KMS wiring is a
one-time ops step (§6) — app code never creates GCP resources (same rule
as Pub/Sub topics and the Cloud Scheduler job).

## 1. Threat model / goals

- A tenant's secret (Telegram bot token, third-party API key) must be
  readable only inside that tenant's request path, never cross-tenant:
  app-layer `tenant_id` filter + Postgres RLS, the same two belts as every
  other `agentcloud_*` table.
- A database dump alone must not disclose secrets: values are
  envelope-encrypted; the KEK lives in Cloud KMS and never touches the DB
  or the app's disk. (The `plaintext-dev` backend intentionally waives
  this property — dev/tests only, loudly named.)
- Secrets never appear in env vars, logs, event payloads, or list
  responses. The read path returns the plaintext to the *tool runtime*
  only, at the moment of use.

## 2. Schema: `agentcloud_tenant_secrets`

Additive, idempotent DDL (app/migrations.py); RLS'd like every
`agentcloud_*` table (tenant policy + admin policy, ENABLE+FORCE).

```sql
CREATE TABLE IF NOT EXISTS agentcloud_tenant_secrets (
    tenant_id   TEXT NOT NULL,
    name        TEXT NOT NULL,      -- e.g. "telegram_bot_token"
    backend     TEXT NOT NULL,      -- 'plaintext-dev' | 'kms' (writer's backend)
    kms_key_ref TEXT,               -- full KMS key resource name (kms rows)
    dek_wrapped BYTEA,              -- KMS-wrapped data-encryption key (kms rows)
    nonce       BYTEA,              -- AES-GCM nonce (kms rows)
    ciphertext  BYTEA NOT NULL,     -- AES-256-GCM ciphertext (kms) | raw value (plaintext-dev)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    rotated_at  TIMESTAMPTZ,        -- set on every overwrite of an existing name
    PRIMARY KEY (tenant_id, name)
)
```

- `name` is a tenant-chosen identifier, 1–128 chars, `[a-z0-9_.-]`
  (validated in `app/secrets.py`). One current value per (tenant, name);
  writing an existing name overwrites and stamps `rotated_at` (no version
  history in B2).
- `backend` records **how the row was encrypted**, so reads decrypt
  correctly even across a backend migration window (a `plaintext-dev` row
  remains readable after `SECRETS_BACKEND=kms` is flipped; new writes use
  the new backend).
- `kms_key_ref` pins the exact key *version-less* resource name used to
  wrap the DEK — decrypt calls pass it verbatim, so key rotation in KMS
  (new primary version) Just Works: KMS decrypts with whichever version
  wrapped it.

## 3. Envelope encryption (backend `kms`)

Write path (`set_secret`):

1. Generate a fresh 256-bit DEK (`os.urandom(32)`) — one per secret value,
   never reused across rows or rewrites.
2. Encrypt the UTF-8 value with **AES-256-GCM** (`cryptography` library),
   fresh 96-bit nonce, AAD = `b"agentcloud:{tenant_id}:{name}"` — binds the
   ciphertext to its row, so a copied ciphertext cannot be replayed under
   another tenant/name even with DB write access.
3. Wrap the DEK with Cloud KMS `Encrypt(name=SECRETS_KMS_KEY,
   plaintext=DEK)` → `dek_wrapped`.
4. Store `(backend='kms', kms_key_ref, dek_wrapped, nonce, ciphertext)`;
   drop the plaintext DEK immediately.

Read path (`get_secret`): KMS `Decrypt(name=kms_key_ref,
ciphertext=dek_wrapped)` → DEK → AES-GCM decrypt with stored nonce + the
same AAD. Runs inside `tenant_session(tenant_id)` — RLS is the second belt
under the app-layer filter. KMS network calls happen **outside** the DB
transaction (same no-conn-during-network discipline as model/embedding
calls).

Backend `plaintext-dev`: `ciphertext` holds the raw UTF-8 value;
`dek_wrapped`/`nonce`/`kms_key_ref` are NULL. Selected only by explicit
config; the name is deliberately alarming in any prod-shaped review.

## 4. Provider abstraction (`app/secrets.py`)

Config-gated exactly like `MODEL_PROVIDER` / `EVENT_BUS`:

- `SECRETS_BACKEND=plaintext-dev` (default — dev/tests, no GCP dependency)
- `SECRETS_BACKEND=kms` (envelope encryption per §3; requires
  `SECRETS_KMS_KEY`; the `google-cloud-kms` client is imported lazily and
  is injectable for tests — unit tests run against a mocked KMS that
  round-trips wrap/unwrap without the network).

API (the only sanctioned access path; tools/adapters must go through it):

```python
await secrets.set_secret(tenant_id, name, value)      # upsert; stamps rotated_at on overwrite
await secrets.get_secret(tenant_id, name)             # -> str | None (decrypted)
await secrets.delete_secret(tenant_id, name)          # -> bool
await secrets.list_secrets(tenant_id)                 # -> [{name, backend, created_at, rotated_at}]  (NEVER values)
```

`SecretDecryptError` is raised (and must be surfaced as a clean tool
error, never a stack trace with material) when a row cannot be decrypted —
wrong KMS permissions, tampered ciphertext/AAD mismatch, unknown backend.

No HTTP surface in B2: nothing exposes secrets over the API yet. The first
consumer (per-tenant Telegram bot tokens, channel adapters — Phase C) adds
its endpoints against this module + this contract.

## 5. KMS naming + IAM (contract for the ops setup)

- **Key ring:** `agentcloud`, location `us-central1` (same region as the
  service), project `totemic-formula-467102-s9`.
- **Key:** `tenant-secrets`, purpose `ENCRYPT_DECRYPT`, rotation period 90
  days (KMS-managed rotation; old versions stay decrypt-capable, so no
  re-encryption sweep is required — `kms_key_ref` rows keep working).
- `SECRETS_KMS_KEY=projects/totemic-formula-467102-s9/locations/us-central1/keyRings/agentcloud/cryptoKeys/tenant-secrets`
- **IAM:** the orchestrator's service account
  (`openclaw-adk@totemic-formula-467102-s9.iam.gserviceaccount.com`) needs
  `roles/cloudkms.cryptoKeyEncrypterDecrypter` **on that key only** — not
  project-wide. No other principal needs decrypt.

## 6. One-time ops setup (not created by app code)

```bash
gcloud kms keyrings create agentcloud \
  --project totemic-formula-467102-s9 --location us-central1
gcloud kms keys create tenant-secrets \
  --project totemic-formula-467102-s9 --location us-central1 \
  --keyring agentcloud --purpose encryption \
  --rotation-period 90d --next-rotation-time +90d
gcloud kms keys add-iam-policy-binding tenant-secrets \
  --project totemic-formula-467102-s9 --location us-central1 --keyring agentcloud \
  --member serviceAccount:openclaw-adk@totemic-formula-467102-s9.iam.gserviceaccount.com \
  --role roles/cloudkms.cryptoKeyEncrypterDecrypter
# then on deploy: SECRETS_BACKEND=kms, SECRETS_KMS_KEY=<resource name above>
```

## 7. Explicit non-goals (B2)

- No secret-version history / point-in-time recovery (overwrite is
  destructive; `rotated_at` records that it happened).
- No automatic re-encryption sweep on backend flip (rows decrypt via their
  recorded `backend`; a sweep is additive later if plaintext-dev rows must
  be purged from a promoted environment).
- No HTTP API, no UI (first consumer arrives with channel adapters).
- No per-secret IAM/audit beyond the standard event/audit machinery —
  reads are not evented in B2 (a `secret.accessed` event is a candidate
  addendum when tools start consuming secrets).
