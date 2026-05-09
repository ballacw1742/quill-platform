# Telegram Bot — Known Issues

Tracking caveats, deferred work, and "fix later" notes for the conversational
bot. Each entry has a severity tag and target sprint.

## Phase G.3 (estimates bot tools)

### G.3.1 No file upload support in bot — use /today on the web app
- **Severity:** `(visible-tolerable)` — by design for v1
- **Discovered:** Phase G.3 design, 2026-05-09
- **What:** The bot has three new tools (`get_estimate_status`,
  `list_recent_estimates`, `estimate_upload_link`) but cannot accept
  PDF / IFC / RVT files via Telegram. Document handlers (and the
  multipart upload plumbing for binary files behind the API's user-
  auth gate) are out of scope for G.3.
- **Workaround:** The `estimate_upload_link` tool returns the web
  deep link (`https://app.quillpm.com/today`); the bot's system
  prompt instructs it to surface that link whenever the user wants
  to start an estimate or sends a file.
- **Target:** Phase G.4 or post-handover; needs MIME sniffing,
  size cap enforcement, and a service-account upload path.

### G.3.2 /v1/estimates and /v1/documents require user JWT — bot uses agent secret
- **Severity:** `(blocking)` for the new tools to work end-to-end against
  the running API; tools work in unit tests but will return
  `unauthorized` against the real API until resolved.
- **Discovered:** Phase G.3 implementation, 2026-05-09
- **What:** Both `/v1/estimates/{id}/status` and `/v1/documents`
  depend on `get_current_user`, which requires a Bearer JWT minted
  via `issue_token(user)`. The Telegram bot only carries the agent
  shared secret (`X-Agent-Secret` + `Authorization: Bearer
  <agent-secret>`), so its requests will 401 against these routes.
- **Mitigation in code:** Both bot tools translate 401 into a
  user-facing `unauthorized` envelope with a pointer to this file,
  rather than crashing the LLM loop.
- **Fix paths (pick one in a follow-up commit — brief forbade API
  changes in this PR):**
  1. Add `Depends(require_agent_secret)` as an alternative auth
     gate on the read-only estimate/document GETs (preferred; one
     OR-of-two dependency).
  2. Mint a long-lived service-account JWT at bot startup and
     attach it to the Authorization header for these routes.
  3. Add a thin admin echo route (e.g. `/v1/admin/estimates/{id}`)
     that the bot can call instead.
- **Target:** Phase G.4 (paired with the file-upload work above).

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

## Phase F.2 (voice notes)

### 7. Voice transcription is English-only
- **Severity:** `(visible-but-tolerable)` for Charles (US-only)
- **What:** `WhisperClient` defaults to `language="en"` which biases
  Whisper-1 toward English transcription. Whisper-1 supports many
  languages but auto-detection isn't enabled.
- **Fix:** drop the `language=` form parameter (or set it from
  per-user preferences) when multi-language support is needed.
- **Target:** Phase F.5 if/when Charles travels or onboards a non-EN
  partner.

### 8. 25 MB upload cap is shared with Telegram
- **Severity:** `(invisible)` in practice
- **What:** Whisper API caps at 25 MB; Telegram's voice-note recorder
  practically caps recordings around 60s/few-MB so this rarely bites.
  We short-circuit before download when `voice.file_size > 25 MB`.
- **Fix:** if Charles ever needs longer recordings, chunk the audio
  via ffmpeg before uploading.
- **Target:** post-handover.

### 9. No TTS reply yet — bot answers with text only
- **Severity:** `(visible-but-tolerable)`
- **What:** Charles records voice, gets text back. Reading on a site
  walk works but a TTS reply would be hands-free end-to-end.
- **Fix:** wire OpenAI's `audio.speech` (TTS-1) into the voice handler
  to optionally reply with an .mp3.
- **Target:** Phase F.5 (explicit deferral).

### 10. Voice audio crosses OpenAI's API (privacy)
- **Severity:** `(visible-but-tolerable)` — documented behaviour
- **What:** Voice files leave the Mac Studio and hit
  `api.openai.com/v1/audio/transcriptions`. OpenAI's data-use policy
  for API calls applies. For fully on-prem transcription we'd run
  whisper.cpp locally.
- **Fix:** swap `WhisperClient` for a local whisper.cpp adapter behind
  the same interface.
- **Target:** post-handover, only if Charles wants on-prem audio.

### 11. Whisper-1 doesn't return per-utterance confidence
- **Severity:** `(invisible)`
- **What:** `TranscriptionResult.confidence` is always `None` because
  Whisper-1's `verbose_json` doesn't report it. The field stays in the
  dataclass so future models (or local whisper.cpp with a softmax
  proxy) can fill it without breaking the consumer contract.
- **Fix:** none required today.
- **Target:** none.
