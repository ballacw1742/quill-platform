# CONTRIBUTING_AGENTS.md — Rules for sub-agents working on Quill

You are a sub-agent dispatched by the Quill orchestrator. **Read this file first.** It exists because past sub-agents have caused integration bugs by improvising contracts. Follow these rules.

---

## 1. Don't invent contracts. Use the canonical ones.

Before writing any code that calls or is called by another service:

- **API ↔ UI contract:** Look at `api/app/schemas.py` for the actual API response shapes. Don't guess. If a field isn't there, ask the orchestrator before adding it.
- **Agent output shapes:** `/Users/charlesmitchell/.openclaw/workspace/agentic-pmo-prompts/schemas/*.schema.json` are the authoritative agent output schemas. Use them verbatim.
- **Approval Queue item shape:** `agentic-pmo-prompts/schemas/approval_queue_item.schema.json` is the wire format. The API stores additional fields (status, audit_hash, etc.) but the agent-submitted core stays as defined.
- **Lane representation:** API uses integer `lane: 1 | 2 | 3` (1 = auto, 2 = single sig, 3 = dual sig). Agent prompts use `tier-0-mandatory | tier-1-spotcheck | tier-2-auto`. The runtime maps prompt-tier → lane. Don't introduce new representations.
- **Role enum:** API uses `owner | partner | viewer | admin`. UI components must accept all of these.
- **Auth header:** API uses `Authorization: Bearer <jwt>`. The UI must store the JWT in `localStorage` after login and attach it to every request via `apiFetch`.
- **Error envelope:** `{ "detail": "<string>" }` for FastAPI errors. UI shows `detail` to the user.
- **List response envelope:** `{ items: [...], total, limit, offset }`. UI must extract `items`.
- **Date format:** ISO-8601 with timezone for everything. America/New_York for display.

If you encounter a real contract gap (e.g., a field the API needs but isn't in the schema), **stop and surface it in your final report** rather than improvising both sides.

## 2. Respect the path scoping in your task brief

Your brief tells you which paths you may modify and which are off-limits. Off-limits means **read-only** — you may reference other code but you may not edit it.

If you genuinely need to touch an off-limits file, say so in your report instead of doing it. The orchestrator will adjudicate.

## 3. Branch-per-subagent

Default to creating a dedicated branch for your work:

```bash
git checkout -b sprint-<n>.<m>-<short-name>
# ... your commits ...
git push -u origin sprint-<n>.<m>-<short-name>
gh pr create --fill
```

Do NOT push directly to `main` unless your brief explicitly says you may.

The orchestrator merges branches to `main` after reviewing your diff. This prevents two parallel sub-agents from racing on the same `main`.

## 4. Don't commit other sub-agents' staged work

Before committing:

```bash
git status              # see what's staged
git diff --stat HEAD    # see what your commit will include
```

If you see files you didn't author (other sub-agent's work), **explicitly stage only your own files** with pathspecs:

```bash
git add path/to/your/file.py path/to/your/other/file.py
git commit -m "..."
```

Never `git add -A` or `git add .` if a parallel sub-agent might have staged something.

## 5. Self-test the integration boundary, not just your unit tests

Unit tests pass + the API server boots != the system works. Before declaring done:

1. **Boot the API** if your work requires it.
2. **Hit the actual endpoints** with curl or a Python httpx call. Confirm shapes match what your code produces/consumes.
3. **Run the canonical happy path** specific to your sprint: e.g., for an auth change, log in via the API and confirm a Bearer-authenticated subsequent call works. For a new agent, run the agent end-to-end and confirm the queue item lands.
4. **If you can't run the boundary test** (e.g., the API isn't up because another sub-agent is rebuilding it), say so in your final report.

## 6. Surface caveats with severity

In your final report, every caveat gets a tag:

- `(invisible)` — internal only; user never notices
- `(visible-tolerable)` — user might notice but it doesn't break anything
- `(visible-frustrating)` — user will hit this in their first hour and be annoyed
- `(blocking)` — this prevents the user from completing the canonical happy path

The orchestrator is responsible for fixing `visible-frustrating` and `blocking` items in the same sprint. Don't bury them.

## 7. .env handling

Services that read env vars (the API, the bot, the runtime) need their env loaded when started. If you write a startup command in a Makefile/script, wrap it:

```bash
bash -c 'set -a; source .env; set +a; exec <your-command>'
```

Don't trust that `.env` is auto-loaded — verify by tailing the service log for at least 5 seconds after startup and confirming no `fake_token_mode=True`, `WARN`, or `missing config` lines.

## 8. Idempotency on writes

If your code creates approval items, posts to vendor APIs, sends Telegram messages, or writes to the audit log: **make it idempotent.**

- Use the request hash as part of the key wherever possible.
- Track sent state in a small SQLite or Postgres table.
- After a process restart, do not re-send what was already sent.

The same applies to feeders/dispatchers: if your daemon restarts, it should not duplicate earlier work.

## 9. Audit log writes go through `record_event_with_mirror`

Anything that mutates state worth replaying or disputing later writes an audit entry. Don't bypass the audit chain. Don't hand-roll a write to the `audit_log_entries` table.

## 10. Never auto-execute approval items

Even with the API + the runtime + auth, the rule is unchanged: **no agent writes to a system of record without a human approval recorded against the item.** Lane 1 ("auto") items still write an audit entry but they only execute pre-approved low-risk classes. If you're unsure whether something qualifies as Lane 1, default to Lane 2.

## 11. Report what you did, not what was easy to say

In your final report:

- **Commit hashes pushed** (real, verified via `git log`)
- **Test pass count** (the actual number from `pytest -q`)
- **Files modified** (`git diff --stat HEAD~N..HEAD`)
- **What you couldn't verify** (be specific: "did not run end-to-end with X because Y")
- **Caveats with severity tags** (per rule 6)

Don't claim things you didn't run. Don't summarize tests as "all green" if you didn't see all green.

---

If anything in your task brief contradicts this file, **stop and ask the orchestrator** which one wins. Don't silently improvise.
