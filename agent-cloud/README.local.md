# Quill Agent Cloud — Local Quick-Start

Run the full Quill Agent Cloud stack locally (or on-prem) with **no GCP
services**. Uses local Postgres, local Ollama inference, and a file-backed
event bus. See [ONPREM.md](ONPREM.md) for the full operator guide.

---

## Prerequisites

| Requirement | Minimum |
|---|---|
| Docker + Docker Compose | v24+ |
| RAM | 8 GB (16 GB recommended for larger models) |
| Disk | 10 GB free (Ollama model storage) |
| age CLI | for `SECRETS_BACKEND=age` (install: `brew install age` or [age releases](https://github.com/FiloSottile/age/releases)) |

---

## 3-command quick-start

```bash
# 1. Generate an age key pair (once — skip if you already have one)
age-keygen -o ~/.agentcloud/age-identity.txt
# Public key is printed: e.g. age1abc123...
# Copy it into step 2 below.

# 2. Set your age public key
export AGE_RECIPIENT="age1abc123..."          # your public key from step 1
export HOST_AGE_IDENTITY_FILE="$HOME/.agentcloud/age-identity.txt"

# 3. Start the stack
docker compose -f docker-compose.local.yml up -d
```

The orchestrator API is available at **http://localhost:8080**.

---

## Pull an Ollama model

After the stack is up, pull at least one model:

```bash
# Pull the default model (llama3.2 ~2 GB)
docker exec quill-ollama ollama pull llama3.2

# Pull the embedding model (required for memory search)
docker exec quill-ollama ollama pull nomic-embed-text

# List available models
docker exec quill-ollama ollama list
```

Change `MODEL_DEFAULT` in `docker-compose.local.yml` to use a different
model (e.g. `mistral`, `phi4`, `qwen2.5`).

---

## Verify it's running

```bash
# Health check
curl http://localhost:8080/health

# Check Ollama is up
curl http://localhost:11434/api/tags
```

---

## Secrets (age backend)

The default `SECRETS_BACKEND=age` requires:

| Variable | Description |
|---|---|
| `AGE_RECIPIENT` | Your age public key (`age1...`) |
| `AGE_IDENTITY_FILE` | Path to the private key file *inside the container* |

To bind-mount your key file into the container, uncomment the volume line in
`docker-compose.local.yml` and set `HOST_AGE_IDENTITY_FILE` to your local key
path.

To skip encryption in development, set `SECRETS_BACKEND=plaintext-dev` (never
use in production).

---

## Stop / restart

```bash
# Stop all services (data volumes are preserved)
docker compose -f docker-compose.local.yml down

# Restart after an upgrade (pull new image, keep data)
docker compose -f docker-compose.local.yml pull
docker compose -f docker-compose.local.yml up -d
```

---

## Logs

```bash
docker compose -f docker-compose.local.yml logs -f agent-cloud
docker compose -f docker-compose.local.yml logs -f postgres
docker compose -f docker-compose.local.yml logs -f ollama
```

---

See [ONPREM.md](ONPREM.md) for backup/restore, configuration reference,
and upgrade guidance.
