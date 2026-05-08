# Voice Notes via Telegram — Spec (Quill v3 Phase F.2)

**Goal:** Charles records a voice note in Telegram on his iPhone, sends it to `@DC_QuillBot`. The bot transcribes it via Whisper, treats the transcript as a normal NL message, runs the existing conversational LLM loop, and replies. End-to-end voice → answer in ~5 seconds.

This is the most natural input mode by far for a busy site walk. Talk faster than you type, hands free, no need to context-switch from Telegram.

## Architecture

```
Voice message in Telegram
       │
       ▼
Telegram bot voice handler
       │
       ▼
Download .ogg audio file from Telegram CDN
       │
       ▼
OpenAI Whisper API (whisper-1) → transcribed text
       │
       ▼
Existing NL handler — feed transcript as if Charles typed it
       │
       ▼
ConversationalLLM loop (already exists)
       │
       ▼
Reply (text in Telegram, optionally TTS via OpenAI in a future phase)
```

## Configuration

New env var: `OPENAI_API_KEY` for Whisper. (Anthropic doesn't have a transcription endpoint, so we use OpenAI's Whisper-1.)

If OPENAI_API_KEY is not set, the voice handler replies: "Voice notes need an OpenAI API key configured. For now, type your message in plain text."

## Implementation plan (3 commits, single subagent)

### Commit 1: Whisper client wrapper
- New file `telegram-bot/quill_bot/transcription.py`:
  - `class WhisperClient`:
    - `__init__(api_key: str | None)`
    - `async transcribe(audio_path: Path | bytes, language: str = "en") -> TranscriptionResult`
    - Uses OpenAI's `audio/transcriptions` endpoint
    - Handles .ogg → .wav conversion if needed (Telegram sends .ogg/Opus by default)
    - Returns `TranscriptionResult(text: str, duration_sec: float, language: str, confidence: float | None)`
  - Tests in `telegram-bot/tests/test_transcription.py` with mocked HTTP.

### Commit 2: Voice handler in the bot
- New file `telegram-bot/quill_bot/handlers/voice.py`:
  - `async handle_voice_message(update: Update, context)` — registered for `MessageHandler(filters.VOICE)`.
  - Flow: download voice file → send to WhisperClient → log transcript to ConversationStore as a user message annotated with `(voice_note: <transcript>)` → run the existing NL turn → send reply.
  - Edge cases: no OPENAI_API_KEY (graceful refusal), file > 25MB (limit; should be very rare for voice notes), Whisper API error (graceful fallback message).
- Update `quill_bot/bot.py` to register the new voice handler AFTER text handlers but on the VOICE filter.
- Update `quill_bot/handlers/__init__.py` exports.
- Tests in `telegram-bot/tests/test_voice_handler.py` with mocked Whisper + mocked Telegram update.

### Commit 3: UX polish + config + docs + verification
- The bot's first reply on a voice note should briefly acknowledge: "Got it ✓ (voice note transcribed)" so the user knows it heard. Then the actual answer follows in the same message or as a quick second message.
- Update `/help` to mention voice notes are supported.
- Document `OPENAI_API_KEY` in `.env.example`.
- Update KNOWN_ISSUES.md.
- Verify: send a real voice note, transcribed, NL loop runs, reply lands. Capture transcript verbatim.
- Open PR: feat/voice-notes → main.

## Cost

- Whisper API: $0.006/minute. Average voice note: ~15s = $0.0015.
- The downstream LLM cost is the same as a text NL turn.
- Tier 4 budget swallows this trivially.

## Caveats baked in

- **English only initially** — language="en" hardcoded; Whisper supports many but Charles is US.
- **Telegram's voice message is always .ogg/Opus** — Whisper accepts ogg directly; no conversion step needed unless we hit a problem.
- **No TTS reply yet** — bot replies in text, you read on screen. TTS reply is Phase F.5 if we want.
- **No long-form recording** — Telegram caps voice messages at ~60s by default. Whisper handles that easily.
- **Privacy:** voice file goes through OpenAI. If you want fully on-prem, we use whisper.cpp locally on the Mac Studio later. Out of scope for this sprint.

## Out of scope

- TTS replies (F.5)
- Multi-language detection
- Long-form recording / .mp3 file uploads
- On-prem Whisper inference
