# Conversational Telegram Spec — Quill v3 Phase B

**Goal:** Replace the bot's slash-command-only interface with natural-language conversation, like Charles talks to Axe in this thread. Slash commands stay as a fallback, but the primary interface is "ask anything in plain English."

## What "good" looks like

Charles types:
- "What's the status of the chiller order?" → bot replies with current Procurement Watcher data on relevant POs.
- "Draft a status update for this week" → bot dispatches the Status Update Author agent, returns a draft as a message + offers to save it as a doc.
- "What RFIs are aged over 48 hours?" → bot lists them as a brief table with deep links.
- "Approve the chiller dunnage RFI" → bot finds the matching item, opens the deep link to the approval sheet on web (passkey ceremony there), confirms when done.
- "What did I sign off yesterday?" → bot pulls from /audit/recent, summarizes.
- "Tell me about Submittal-DC1-A-0234" → bot fetches, summarizes status, citations, what's pending.

Plus: open-ended back-and-forth. "Why is that flagged?" / "Show me the spec section." / "What did the EOR say last week?" — all of it.

## Architecture

```
Telegram message
    │
    ▼
Bot's NL handler (new)
    │
    ▼
Claude (Sonnet 4.6) with:
  - System prompt: "You are Quill, a project assistant…"
  - Tool-use loop: bot exposes a set of API-backed tools as functions
  - Per-chat conversation history (last N turns)
    │
    ▼
Bot executes tool calls:
  - search_approvals(query, lane?, status?)
  - get_approval(id)
  - get_audit(approval_id?, since?, action_type?)
  - get_agent_status(agent_id?)
  - get_health()
  - dispatch_agent(agent_id, input_payload, dry_run=true)
  - generate_deep_link(approval_id, intent)
  - search_documents(query)            ← Phase D
  - get_document(id)                   ← Phase D
    │
    ▼
Claude composes a reply using tool results.
    │
    ▼
Bot sends reply (Markdown formatting, deep links inline)
```

## Components

### 1. `quill_bot/conversation.py` (new)

Per-chat conversation state, stored in a small SQLite DB at `~/.quill/bot-conversation.db`:

```python
class ConversationStore:
    def append(chat_id: int, role: Literal["user","assistant","tool"], content, tool_calls=None, tool_call_id=None) -> None
    def history(chat_id: int, max_messages: int = 24) -> list[Message]
    def reset(chat_id: int) -> None  # bot command /reset
    def trim(chat_id: int, keep: int = 24) -> None  # background trim
```

Storage is per chat_id (Telegram chat). 24-turn rolling window by default. Reset on `/reset` command.

### 2. `quill_bot/llm.py` (new)

Wrapper over Anthropic SDK that does the conversational loop.

```python
class ConversationalLLM:
    def __init__(client: AsyncAnthropic, system_prompt: str, tools: list[ToolDef]): ...
    async def turn(self, messages: list[Message]) -> AssistantTurn:
        """One turn: feed history + tools, run Claude, execute any tool calls,
        feed back, repeat until Claude returns a stop_reason of 'end_turn'.
        Returns the final assistant message + cumulative tool-call log."""
```

System prompt (in `quill_bot/prompts/conversation_system.md`):

```
You are Quill, the project assistant for a $10B hyperscale data center
construction program owned by Charles Mitchell. You help Charles and his team
manage the project by answering questions, drafting documents, surfacing risks,
and routing work to specialist helpers (agents).

Talk like a senior project chief of staff. Direct, calm, plain English. No
project-management jargon unless Charles uses it first.

You have a set of tools that let you read the project's data and dispatch
helpers. Always prefer reading data over guessing. If you need to perform
a write (approve an item, send an email), explain what you propose and ask
Charles to confirm — never write without explicit confirmation.

For approval decisions: never claim to have approved anything. The user must
sign with their passkey on the web app or in person. You generate a deep
link and tell them.

Format messages for Telegram: Markdown (V2 escaped where needed), inline
links allowed, keep replies under ~250 words unless asked for more, use
bullets and short paragraphs.

If the user's message is conversational/non-actionable ("hey, good morning"),
respond briefly and warmly without invoking tools.
```

### 3. `quill_bot/tools.py` (new)

Tool definitions in Anthropic's tool-use schema. Each tool wraps an existing
`ApiClient` method or a small helper.

Tools to ship in Phase B:

| Tool name | Inputs | Returns |
|---|---|---|
| `search_approvals` | `query?: str, lane?: int, status?: str, limit?: int` | List of compact approval summaries |
| `get_approval` | `id: str` | Full approval detail (relevant fields, no raw JSON) |
| `get_audit` | `since?: ISO ts, action_type?: str, approval_id?: str, limit?: int` | List of audit entries |
| `get_agent_status` | `agent_id?: str` | Agent metadata (or list) |
| `get_health` | — | Fleet health snapshot |
| `dispatch_agent` | `agent_id: str, input_payload: dict, summary: str` | Confirmation that the agent ran in dry_run mode + the resulting approval_id (queued, not executed) |
| `generate_deep_link` | `approval_id: str, intent: 'approve'|'reject'|'edit'|'view', reason?: str` | Signed deep link URL with TTL |
| `current_time` | — | ISO timestamp + day of week + project phase |
| `whoami` | — | Charles's session info (so the bot knows who's asking) |

Each tool is a Python async function. The bot's NL handler calls Claude with
the tool list; Claude requests tool calls; bot executes; bot feeds results
back to Claude; Claude composes the reply.

### 4. `quill_bot/handlers/nl.py` (new)

The Telegram handler that catches all *non-command* text messages. It:

1. Reads the message + chat_id.
2. Looks up the user via the existing pairing (`telegram_chat_id → user_id`).
3. If unpaired, replies with the pairing instructions.
4. Loads conversation history.
5. Appends the user's message.
6. Runs `ConversationalLLM.turn(...)`.
7. Sends the assistant's reply back to Telegram.
8. Persists the assistant message + any tool-call evidence.

If Claude returns a tool-use that Charles needs to confirm (e.g., "I'm about
to dispatch the Status Update Author"), the bot replies with the proposal +
inline keyboard buttons "Yes, do it" / "No, cancel" — same pattern Telegram
uses for booking flows.

### 5. Slash commands stay (graceful fallback)

`/queue`, `/health`, `/approve`, `/reject`, `/edit`, `/escalate`, `/brief`,
`/help`, `/start`, `/reset`. If a user types a command, it bypasses the LLM
loop. Discoverability stays.

## Cost & latency

- Sonnet 4.6 with prompt caching on the system prompt + tool definitions →
  cached after first turn, so each subsequent turn is ~$0.005-0.02 depending
  on history length and tool calls.
- Latency: 2-5s per turn typical, up to 8s when 2+ tools are called.
- Budget: ~$10-30/month at Charles's expected use rate.

## Testing

- `quill_bot/tests/test_conversation.py` — store + history trimming.
- `quill_bot/tests/test_tools.py` — each tool round-trips through a mocked API client.
- `quill_bot/tests/test_nl_handler.py` — end-to-end with a mocked Anthropic client and a fake Telegram update.
- `quill_bot/tests/test_llm_loop.py` — multi-tool-call sequence completes correctly.

## Migration

- New deps: `anthropic` (already in pyproject? if not, add).
- New env: `ANTHROPIC_API_KEY` (already set), `BOT_LLM_MODEL` (default "claude-sonnet-4-6"), `BOT_LLM_MAX_HISTORY` (default 24).
- Existing slash command handlers stay; add the new NL handler as a fallthrough on `MessageHandler(filters.TEXT & ~filters.COMMAND)`.

## Out of scope

- Voice messages (transcription via Whisper) — future.
- Image/file uploads — future.
- Multi-user channels (group chats) — single-user DMs only for now.
- Persistent memory across many days — 24-turn rolling is enough for now.

## Hard rules

- The bot **never writes to a system of record**. Every Procore/P6/ACC write
  goes through the existing approval queue + passkey ceremony on the web app.
- The bot **never drafts external comms (sub or hyperscaler) and sends them**.
  It can draft them as messages for Charles to review and copy/forward, or
  dispatch the Comms Drafter agent which produces an approval-queued message.
- The bot **never approves anything itself**. It produces deep links; Charles
  taps the link and approves with Face ID on the web.
- The bot **never invents data**. If a tool call fails or returns nothing,
  the reply says so plainly; it doesn't guess.
