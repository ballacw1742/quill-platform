# ONPREM.md — On-Prem Operator Guide

**Audience:** operators deploying Quill Agent Cloud on-premises or in an
air-gapped environment. This document covers the local stack only — no GCP,
no Cloud Scheduler, no Pub/Sub, no Cloud KMS.

> For the cloud-hosted deployment, see `CUTOVER.md`. For the quick-start
> (three commands), see `README.local.md`.

---

## 1. Prerequisites

| Requirement | Details |
|---|---|
| Docker Engine | v24 or later |
| Docker Compose | v2.20 or later (plugin, not standalone) |
| RAM | 8 GB minimum; 16 GB recommended for 7B+ parameter models |
| Disk | 10 GB free minimum (Ollama model storage grows per model pulled) |
| CPU | x86-64 or ARM64 (Apple Silicon); GPU is optional — Ollama uses CPU by default |
| age CLI | Required for `SECRETS_BACKEND=age`; install via `brew install age` on macOS or download from https://github.com/FiloSottile/age/releases |
| Network | Outbound internet only for initial image/model pulls; after that, fully air-gapped operation is supported |

---

## 2. Quick Start (3 commands)

```bash
# Generate a key pair (once per deployment):
age-keygen -o ~/.agentcloud/age-identity.txt   # prints the public key

export AGE_RECIPIENT="age1..."                  # paste your public key
export HOST_AGE_IDENTITY_FILE="$HOME/.agentcloud/age-identity.txt"

docker compose -f docker-compose.local.yml up -d
```

The orchestrator API is available at **http://localhost:8080**.

Pull at least one Ollama model before making inference requests:

```bash
docker exec quill-ollama ollama pull llama3.2
docker exec quill-ollama ollama pull nomic-embed-text   # for memory search
```

---

## 3. Services

| Service | Image | Port | Purpose |
|---|---|---|---|
| `postgres` | `postgres:16` | (internal) | Persistent state (agents, sessions, secrets, events) |
| `ollama` | `ollama/ollama:latest` | `11434` | Local LLM + embedding inference |
| `agent-cloud` | built from `Dockerfile` | `8080` | Quill orchestrator API |

All three services must be healthy before `agent-cloud` accepts requests.
Health checks are configured in `docker-compose.local.yml`.

---

## 4. Configuration Reference

All configuration is via environment variables passed to the `agent-cloud`
service. Defaults are set in `docker-compose.local.yml`; override by setting
the variable in the environment before running `docker compose up`, or by
creating a `.env.local` file and passing `--env-file .env.local`.

### Core local-stack variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://quill:quill@postgres:5432/agentcloud` | PostgreSQL connection string |
| `MODEL_PROVIDER` | `local` | Use `local` for Ollama inference |
| `LOCAL_OLLAMA_BASE` | `http://ollama:11434` | Ollama base URL (internal Docker network) |
| `MODEL_DEFAULT` | `llama3.2` | Default inference model; must be pulled first |
| `MODEL_CHEAP` | `llama3.2` | Budget/fast model; can differ from MODEL_DEFAULT |
| `EMBEDDING_PROVIDER` | `local` | Use `local` for Ollama embeddings |
| `LOCAL_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model; must be pulled |
| `EVENT_BUS` | `file` | `file` = local durable JSONL bus; `inline` = in-process only |
| `EVENT_BUS_FILE` | `/data/events/events.jsonl` | Path inside container for the JSONL event log |
| `JOBS_BACKEND` | `local` | `local` = in-process asyncio tasks (no Cloud Run) |
| `SCHEDULER_BACKEND` | `loop` | `loop` = in-process tick loop (no Cloud Scheduler) |
| `SECRETS_BACKEND` | `age` | `age` = age KEK encryption; `plaintext-dev` = dev only |
| `AGE_RECIPIENT` | *(required)* | age public key (`age1...`) for encrypting secrets |
| `AGE_IDENTITY_FILE` | `/run/secrets/age-identity` | Path *inside container* to the age private key |
| `SERVICE_AUTH_SECRET` | *(set to a strong random value)* | Shared secret for internal API routes |
| `LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |

### Supported Ollama models (examples)

| Model | Size | Notes |
|---|---|---|
| `llama3.2` | ~2 GB | Good default; fast on CPU |
| `mistral` | ~4 GB | Strong instruction following |
| `phi4` | ~8 GB | Compact, capable |
| `qwen2.5` | ~4 GB | Good multilingual support |
| `nomic-embed-text` | ~274 MB | Embedding model (required for memory search) |

Pull a model: `docker exec quill-ollama ollama pull <model-name>`

---

## 5. age Key Management (SECRETS_BACKEND=age)

The `age` backend encrypts each secret value with the recipient's public key.
Only the holder of the matching private key (the identity file) can decrypt.

### Generate a key pair

```bash
age-keygen -o ~/.agentcloud/age-identity.txt
# Output: Public key: age1abc123...
```

Store the private key file securely. It is the only thing that can decrypt
your secrets. Back it up separately from the Postgres volume.

### Bind-mount the key into the container

Uncomment the `volumes` section for the age identity in
`docker-compose.local.yml` and set `HOST_AGE_IDENTITY_FILE`:

```bash
export HOST_AGE_IDENTITY_FILE="$HOME/.agentcloud/age-identity.txt"
docker compose -f docker-compose.local.yml up -d
```

### Key rotation

1. Generate a new key pair with `age-keygen`.
2. Update `AGE_RECIPIENT` to the new public key.
3. Update `HOST_AGE_IDENTITY_FILE` to the new private key path.
4. Existing rows in `agentcloud_tenant_secrets` are tagged `backend='age'`
   with the old recipient in `kms_key_ref`. They will remain decryptable only
   with the old private key. Re-encrypt them by reading each secret (old key)
   and re-writing (new key) during a maintenance window.

---

## 6. FileBus — Durable Event Log (EVENT_BUS=file)

The `file` bus writes every event as a JSONL line to `EVENT_BUS_FILE` and
also dispatches events inline to in-process subscribers. On startup, `replay()`
reads from the last cursor offset to EOF, re-dispatching any events that were
written but not yet processed before a previous shutdown.

The cursor file (same directory, suffix `.cursor`) records the last-processed
byte offset. It survives container restarts as long as the `events_data` volume
is persisted.

**Single-node only.** The `file` bus has no distributed locking and is not
safe for multi-replica deployments. Use `pubsub` for multi-node.

---

## 7. What Is NOT Included

This on-prem stack intentionally omits all GCP-specific services:

| Excluded | Reason |
|---|---|
| Google Cloud KMS | Replaced by `age` local KEK |
| Google Cloud Pub/Sub | Replaced by `FileBus` (JSONL + cursor) |
| Google Cloud Run Jobs | Sub-agents run as local asyncio tasks (`JOBS_BACKEND=local`) |
| Google Cloud Scheduler | Scheduling uses an in-process tick loop (`SCHEDULER_BACKEND=loop`) |
| Vertex AI / Gemini API | Inference uses local Ollama; embeddings use `nomic-embed-text` via Ollama |
| Cloud SQL | Replaced by local PostgreSQL 16 in Docker |

This is a deliberate design choice for air-gapped, offline, or cost-sensitive
deployments where GCP connectivity is not available or not desired. The
application code is identical — only the backend implementations change via
environment variables.

---

## 8. Backup and Restore

### Postgres data

```bash
# Backup (while stack is running)
docker exec quill-postgres pg_dump -U quill agentcloud | gzip > agentcloud_backup_$(date +%Y%m%d).sql.gz

# Restore
gunzip < agentcloud_backup_YYYYMMDD.sql.gz | docker exec -i quill-postgres psql -U quill agentcloud
```

### Ollama models

Ollama models are stored in the `ollama_models` volume. They are re-pullable
from the internet; you do not need to back them up unless offline operation is
required.

```bash
# Back up models (large — only needed for offline environments)
docker run --rm -v ollama_models:/data -v $(pwd):/backup alpine \
  tar czf /backup/ollama_models.tar.gz -C /data .
```

### age private key

Back up `~/.agentcloud/age-identity.txt` (or wherever you store your private
key) separately from all Docker volumes. Without it, `agentcloud_tenant_secrets`
rows tagged `backend='age'` cannot be decrypted.

### Event log

The `events_data` volume holds the JSONL event log and cursor file. Back it up
alongside the Postgres dump if you need full event replay capability.

---

## 9. Upgrading

```bash
# Pull the latest image
docker compose -f docker-compose.local.yml pull agent-cloud

# Restart the service (data volumes are preserved)
docker compose -f docker-compose.local.yml up -d agent-cloud
```

Migrations are applied automatically on startup via `app/migrations.py`.
No manual schema changes are required for minor upgrades.

---

## 10. Troubleshooting

| Symptom | Check |
|---|---|
| `agent-cloud` exits immediately | Check `docker compose logs agent-cloud`; likely a missing env var or Postgres not yet healthy |
| `ollama` healthcheck failing | Wait 30s for ollama to start; check `docker compose logs ollama` |
| `SecretDecryptError: age identity file not found` | Verify `AGE_IDENTITY_FILE` points to a mounted, readable file inside the container |
| `ImportError: Install pyrage: pip install pyrage` | The `pyrage` package is missing from the image; rebuild with `docker compose build` |
| Memory search returns no results | Pull `nomic-embed-text` via `docker exec quill-ollama ollama pull nomic-embed-text` |
| Inference is very slow | Ollama defaults to CPU; expected for large models. Use `phi4` or `llama3.2` (smaller) for faster responses |

---

*Phase 4 deliverable — §9.5 local-first packaging. No GCP required.*
