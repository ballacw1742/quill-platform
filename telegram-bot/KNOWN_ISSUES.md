# Telegram Bot — Known Issues

Tracking caveats, deferred work, and "fix later" notes for the conversational
bot. Each entry has a severity tag and target sprint.

## Phase B (conversational bot)

### 1. `ANTHROPIC_API_KEY` not configured in `.env` — blocking e2e test
- **Severity:** `(blocking)` for end-to-end conversational use
- **Discovered:** Phase B Commit 7 verification, 2026-05-08
- **What:** The conversational handler depends on
  `anthropic.Anthropic()` finding an API key (env var, config file, or
  service account). The repo's `.env` does not export
  `ANTHROPIC_API_KEY`; the running bot starts but its first NL message
  errors with `Could not resolve authentication method`. Sub-agent
  could not verify the 10-step Telegram e2e; only static + unit tests
  ran.
- **Mitigation in code:** `bot.py` catches the construction failure and
  sets `llm = None`; the handler then surfaces a graceful error
  message rather than crashing the process.
- **Fix:** add `ANTHROPIC_API_KEY=sk-ant-...` to `.env` and restart the
  bot service. Once set, no code changes are required — the loop is
  unit-test-validated.
- **Target:** before Phase C kicks off.

### 2. Bot process running pre-conversational code (needs restart)
- **Severity:** `(visible-and-frustrating)` until restarted
- **What:** PID 4630 has been running since 2:40 AM ET (commit
  `421f246` era). It still serves slash commands but does NOT have
  the new NL handler, /reset command, or updated /help. Telegram
  message-handler registration happens once at startup.
- **Fix:** stop the existing `quill-bot` process and restart with
  `.env` sourced (per LESSONS #8). A `bin/start-all.sh` would prevent
  this regression.
- **Target:** same restart as fix #1.

### 3. Confirmation flow is acknowledgement-only (Phase D will wire it)
- **Severity:** `(invisible)` for read-mostly use
- **What:** When Claude calls `dispatch_agent`, the tool layer always
  runs `--no-submit` (dry-run). The Yes/No buttons collect user
  consent but don't yet trigger a non-dry-run runtime invocation —
  the Yes branch logs "I'll route this through agent X once the
  non-dry-run path is enabled (Phase D)." The user-visible behavior
  is correct ("nothing was written"), but a power user expecting Yes
  to actually queue an item will be mildly surprised.
- **Fix:** in Phase D, replace the Yes branch in
  `handlers/nl.handle_nl_confirm` with a real
  `quill-runtime run <agent> --input - --submit` invocation.
- **Target:** Phase D.

### 4. NL replies use `Markdown`, not `MarkdownV2`
- **Severity:** `(visible-but-tolerable)`
- **What:** The CONVERSATIONAL_SPEC suggests `MarkdownV2` (with
  per-character escaping). The actual handler uses `reply_markdown`
  (legacy Markdown), matching the rest of the bot for consistency.
  Some characters that need escaping in V2 (`-`, `.`, `!`) render
  fine in legacy Markdown, but Claude could in principle emit a
  string that breaks legacy parsing — the handler catches that and
  falls back to plain text, so the message still gets through.
- **Fix:** if/when we move the entire bot to V2, do it as one
  coordinated change (decisions.py, queue.py, health.py, nl.py).
- **Target:** post-handover polish.

### 5. `whoami` tool calls a non-existent admin endpoint
- **Severity:** `(invisible)` — handled gracefully
- **What:** `tools._exec_whoami` hits
  `GET /v1/admin/users/by_chat/{chat_id}`, which the API does not
  expose yet. The 404 is caught and the tool returns
  `{paired: false}`. The NL handler now uses `DedupStore.get_paired_email`
  for the canonical pairing check, so this is mostly a cosmetic
  inconsistency — `whoami` still works as a Claude-callable tool but
  reports `paired: false` even when the chat IS paired.
- **Fix:** add `GET /v1/admin/users/by_chat/{chat_id}` to the API
  (or rewrite `_exec_whoami` to consult the DedupStore directly).
- **Target:** Phase C alongside the user/role surface.

### 6. ConversationStore is per-chat with no archival policy
- **Severity:** `(invisible)` for current scale
- **What:** Each chat keeps a 24-message rolling window in
  `~/.quill/bot-conversation.db`. There's no GC of old chats, no
  archival to long-term memory, and no cross-chat sharing. Single
  user, single bot — fine for now.
- **Fix:** if multi-user, add per-chat GC + maybe upload Trim'd
  history to Drive for future replay.
- **Target:** post-handover.
