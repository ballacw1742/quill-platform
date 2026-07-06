# quill-dispatch-worker — Quill dispatch loops on Cloud Run

> **Naming note:** the sprint brief called this service `quill-worker`, but
> that Cloud Run service name was already taken by the dev-chat Cloud Tasks
> consumer (built from `worker/`, deployed 2026-06-28). This service is
> therefore `quill-dispatch-worker`.

Sprint 5.5. This service replaces the four launchd daemons that used to run
on Charles's Mac Studio (`com.quill.contract-dispatcher`,
`com.quill.contract-review-dispatcher`, `com.quill.classify-dispatcher`,
`com.quill.estimate-dispatcher`). The demo no longer depends on a Mac being
awake.

## What it runs

One container, four supervised asyncio loops (from `runtime/runtime/`):

| Loop | Agent | Picks up | Produces |
|---|---|---|---|
| contract | contract-extractor | contracts `status=extracted`, no fields | `contract_extraction.publish` approval |
| contract_review | contract-reviewer | contracts extracted + fields, no review | `contract_review.publish` approval |
| classification | design-classifier | estimates `status=queued` | `aace_classification.publish` approval |
| estimator | estimator-scheduler | estimates `status=estimating` | `cost_schedule_package.publish` approval |

Crashed loops restart with exponential backoff (5s → 5m). `GET /healthz`
reports per-loop liveness; `GET /statusz` reports state-store counts.

## Architecture decisions

**State — Postgres, direct connection (not an API endpoint).**
Dispatcher dedupe/claim state lives in a `runtime_dispatch_state` table
(created by the worker itself, `CREATE TABLE IF NOT EXISTS`; not managed by
API Alembic migrations, so worker deploys are decoupled from API deploys).
`try_claim` is a single atomic `INSERT … ON CONFLICT DO UPDATE … WHERE`
statement with a 15-minute lease, so N replicas can never double-process an
upload, crashed claims become stealable, and errored items respect
exponential backoff (30s·2^n, capped at 5m — same policy as the old JSON
files). Why direct DB instead of a new agent-state API endpoint: (1) the
API routes were an off-limits surface this sprint (a parallel agent owns
them), (2) claim semantics need real transactional atomicity — an HTTP
endpoint would just re-implement the same SQL behind a slower, less
reliable hop, and (3) the worker already lives in the same GCP project and
attaches to Cloud SQL over the private unix socket with a Secret Manager
ref — no new credential surface. Revisit toward an API-owned endpoint if
the worker ever moves out of the project boundary.

**Auth — X-Agent-Secret only, no owner JWT.**
The Mac daemons authenticated with the shared agent secret
(`AGENT_SHARED_SECRET` header `X-Agent-Secret`, see
`api/app/security.py::require_agent_secret`); they never held a human JWT.
The worker replicates exactly that. Approvals are still decided by humans
in the web UI / gates — the worker only *creates* approval items and reads
contract/estimate state, all of which the agent-secret path authorizes.

**Prompts — vendored snapshot baked into the image.**
`prompts/` contains the four agents' `system.md` + the full schemas dir,
pinned to a commit of `agentic-pmo-prompts` (see `prompts/README.md`).
`PROMPTS_REPO_PATH=/app/prompts`. No network or Mac-filesystem dependency.

**Blobs — fetched over HTTP.**
Extracted text/blobs come from the Sprint 4 endpoints
(`GET /v1/{contracts,estimates}/{id}/extracted/{filename}`) since the local
blob dir doesn't exist in the container. This was already the remote-daemon
code path; nothing new.

## Configuration (env)

| Var | Source | Notes |
|---|---|---|
| `QUEUE_API_URL` | env | `https://quill-agents-894031978246.us-central1.run.app` |
| `AGENT_SHARED_SECRET` | Secret Manager `QUILL_AGENT_SECRET` | X-Agent-Secret |
| `ANTHROPIC_API_KEY` | Secret Manager `ANTHROPIC_API_KEY` | LLM calls |
| `RUNTIME_STATE_DATABASE_URL` | Secret Manager `QUILL_DATABASE_URL` | required; worker refuses to boot without it |
| `PROMPTS_REPO_PATH` | baked into image | `/app/prompts` |
| `QUILL_WORKER_DISPATCHERS` | env (optional) | comma list; default all four |
| `*_POLL_INTERVAL_SECONDS` | env (optional) | per-dispatcher poll tuning |

Deploy: `.github/workflows/worker-deploy.yml` (paths `runtime/**`,
`dispatch-worker/**`). Cloud Run service `quill-dispatch-worker`, min-instances=1,
CPU always allocated, Cloud SQL instance attached, no unauthenticated
ingress (health checks via ID-token curl).

## One-time state migration

`scripts/import_state.py` seeds `runtime_dispatch_state` from the Mac
daemons' JSON state files so the worker doesn't re-dispatch historical
uploads. Run once at cutover (see script docstring).
