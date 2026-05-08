"""Tests for the voice-note Telegram handler (Phase F.2 — Commit 2)."""

from __future__ import annotations

from typing import Any

import pytest

from quill_bot.config import BotConfig
from quill_bot.conversation import ConversationStore
from quill_bot.dedup import get_store as get_dedup_store
from quill_bot.handlers import nl, voice
from quill_bot.llm import ConversationalLLM
from quill_bot.transcription import (
    TranscriptionAPIError,
    TranscriptionResult,
    WhisperClient,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _Block:
    def __init__(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


class _Usage:
    input_tokens = 0
    output_tokens = 0
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0


class _Resp:
    def __init__(self, *, stop_reason: str, content: list[Any]):
        self.stop_reason = stop_reason
        self.content = content
        self.usage = _Usage()


class _Messages:
    def __init__(self, scripted: list[_Resp]):
        self._scripted = scripted
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _Resp:
        self.calls.append(kwargs)
        return self._scripted.pop(0)


class FakeAnthropic:
    def __init__(self, scripted: list[_Resp]):
        self.messages = _Messages(scripted)


class _FakeAPI:
    async def list_pending(self, *, lane=None, limit=10, offset=0):
        return []

    async def health(self):
        return {"ok": True, "queue_depth_pending": 0, "audit_chain": "ok"}

    async def _req(self, *args, **kw):
        return []


class FakeWhisper:
    """In-memory WhisperClient stand-in. Lets us script available/transcribe."""

    def __init__(
        self,
        *,
        available: bool = True,
        result: TranscriptionResult | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._available = available
        self._result = result or TranscriptionResult(
            text="What's pending today?",
            duration_sec=2.4,
            language="english",
        )
        self._exc = exc
        self.transcribe_calls: list[dict[str, Any]] = []

    @property
    def is_available(self) -> bool:
        return self._available

    async def transcribe(
        self,
        audio: Any,
        *,
        mime_type: str = "audio/ogg",
        filename: str = "voice.ogg",
    ) -> TranscriptionResult:
        self.transcribe_calls.append(
            {"audio": bytes(audio) if not isinstance(audio, bytes) else audio,
             "mime_type": mime_type, "filename": filename}
        )
        if self._exc is not None:
            raise self._exc
        return self._result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def conv_store(tmp_path) -> ConversationStore:
    return ConversationStore(tmp_path / "conv.db")


@pytest.fixture
def paired_chat(bot_config: BotConfig):
    """A chat_id pre-paired in the dedup store. Returns the chat_id."""
    chat_id = 5550001
    dedup = get_dedup_store()
    dedup.claim_pairing(
        "test-pair-code", email="charles@example.com", chat_id=str(chat_id)
    )
    return chat_id


# ---------------------------------------------------------------------------
# Tests for the pure-logic core: process_voice_message
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unpaired_chat_gets_pairing_reply(
    bot_config: BotConfig, conv_store: ConversationStore
) -> None:
    fake_anthropic = FakeAnthropic([])  # not called in unpaired path
    llm = ConversationalLLM(fake_anthropic)
    whisper = FakeWhisper(available=True)

    reply, pending, transcription = await voice.process_voice_message(
        audio_bytes=b"\x00\x01",
        chat_id=999_111_222,  # never paired
        api=_FakeAPI(),
        config=bot_config,
        llm=llm,
        conv_store=conv_store,
        dedup_store=get_dedup_store(),
        whisper=whisper,
    )

    assert reply == nl.UNPAIRED_REPLY
    assert pending == []
    assert transcription is None
    # No Whisper call was made.
    assert whisper.transcribe_calls == []


@pytest.mark.asyncio
async def test_whisper_unavailable_returns_fallback(
    bot_config: BotConfig, conv_store: ConversationStore, paired_chat: int
) -> None:
    fake_anthropic = FakeAnthropic([])
    llm = ConversationalLLM(fake_anthropic)
    whisper = FakeWhisper(available=False)

    reply, pending, transcription = await voice.process_voice_message(
        audio_bytes=b"\x00\x01",
        chat_id=paired_chat,
        api=_FakeAPI(),
        config=bot_config,
        llm=llm,
        conv_store=conv_store,
        dedup_store=get_dedup_store(),
        whisper=whisper,
    )

    assert reply == voice.WHISPER_UNCONFIGURED_REPLY
    assert pending == []
    assert transcription is None
    assert whisper.transcribe_calls == []


@pytest.mark.asyncio
async def test_empty_transcript_replies_couldnt_make_out(
    bot_config: BotConfig, conv_store: ConversationStore, paired_chat: int
) -> None:
    fake_anthropic = FakeAnthropic([])
    llm = ConversationalLLM(fake_anthropic)
    whisper = FakeWhisper(
        available=True,
        result=TranscriptionResult(text="   ", duration_sec=0.5, language="english"),
    )

    reply, pending, transcription = await voice.process_voice_message(
        audio_bytes=b"\x00\x01",
        chat_id=paired_chat,
        api=_FakeAPI(),
        config=bot_config,
        llm=llm,
        conv_store=conv_store,
        dedup_store=get_dedup_store(),
        whisper=whisper,
    )

    assert reply == voice.EMPTY_TRANSCRIPT_REPLY
    assert pending == []
    assert transcription is not None
    # Conversation history shouldn't have been touched.
    assert conv_store.history(paired_chat) == []


@pytest.mark.asyncio
async def test_transcribe_api_error_returns_graceful_message(
    bot_config: BotConfig, conv_store: ConversationStore, paired_chat: int
) -> None:
    fake_anthropic = FakeAnthropic([])
    llm = ConversationalLLM(fake_anthropic)
    whisper = FakeWhisper(
        available=True,
        exc=TranscriptionAPIError(500, "boom"),
    )

    reply, pending, transcription = await voice.process_voice_message(
        audio_bytes=b"\x00\x01",
        chat_id=paired_chat,
        api=_FakeAPI(),
        config=bot_config,
        llm=llm,
        conv_store=conv_store,
        dedup_store=get_dedup_store(),
        whisper=whisper,
    )

    assert reply == voice.TRANSCRIBE_FAILED_REPLY
    assert pending == []
    assert transcription is None


@pytest.mark.asyncio
async def test_happy_path_runs_llm_and_persists_history(
    bot_config: BotConfig, conv_store: ConversationStore, paired_chat: int
) -> None:
    # Script Claude to say one final-text-only response.
    fake_anthropic = FakeAnthropic(
        [
            _Resp(
                stop_reason="end_turn",
                content=[_Block(type="text", text="Two items pending. Top one is the chiller RFI.")],
            )
        ]
    )
    llm = ConversationalLLM(fake_anthropic)
    whisper = FakeWhisper(
        available=True,
        result=TranscriptionResult(
            text="What's pending today?", duration_sec=3.1, language="english"
        ),
    )

    reply, pending, transcription = await voice.process_voice_message(
        audio_bytes=b"ogg-payload",
        chat_id=paired_chat,
        api=_FakeAPI(),
        config=bot_config,
        llm=llm,
        conv_store=conv_store,
        dedup_store=get_dedup_store(),
        whisper=whisper,
    )

    assert reply == "Two items pending. Top one is the chiller RFI."
    assert pending == []
    assert transcription is not None
    assert transcription.text == "What's pending today?"

    # Whisper saw the audio bytes verbatim.
    assert whisper.transcribe_calls[0]["audio"] == b"ogg-payload"

    # Conversation history: user transcript (with voice tag) + assistant.
    history = conv_store.history(paired_chat)
    assert len(history) == 2
    assert history[0].role == "user"
    assert "[voice note" in (history[0].content or "")
    assert "What's pending today?" in (history[0].content or "")
    assert history[1].role == "assistant"
    assert history[1].content == "Two items pending. Top one is the chiller RFI."


@pytest.mark.asyncio
async def test_format_voice_user_content_short_clip() -> None:
    res = TranscriptionResult(text="hi", duration_sec=0.2, language="english")
    out = voice._format_voice_user_content("hi", res)
    assert out == "[voice note] hi"


@pytest.mark.asyncio
async def test_format_voice_user_content_with_duration() -> None:
    res = TranscriptionResult(text="hi", duration_sec=3.4, language="english")
    out = voice._format_voice_user_content("hi", res)
    # Rounded to nearest second.
    assert out == "[voice note · 3s] hi"


# ---------------------------------------------------------------------------
# Tests for the Telegram adapter handle_voice_message.
# These exercise the full wiring with mock Telegram update/context objects.
# ---------------------------------------------------------------------------
class _FakeTelegramFile:
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def download_as_bytearray(self) -> bytearray:
        return bytearray(self._content)


class _FakeTelegramBot:
    def __init__(self, voice_bytes: bytes) -> None:
        self._voice_bytes = voice_bytes
        self.get_file_calls: list[str] = []

    async def get_file(self, file_id: str) -> _FakeTelegramFile:
        self.get_file_calls.append(file_id)
        return _FakeTelegramFile(self._voice_bytes)


class _FakeApplication:
    def __init__(self, bot: _FakeTelegramBot, bot_data: dict[str, Any]) -> None:
        self.bot = bot
        self.bot_data = bot_data


class _FakeContext:
    def __init__(self, app: _FakeApplication) -> None:
        self.application = app
        self.user_data: dict[str, Any] = {}


class _FakeMessage:
    def __init__(self, voice_obj: Any) -> None:
        self.voice = voice_obj
        self.replies_markdown: list[tuple[str, Any]] = []
        self.replies_text: list[str] = []

    async def reply_markdown(self, text: str, **kwargs: Any) -> None:
        self.replies_markdown.append((text, kwargs))

    async def reply_text(self, text: str, **kwargs: Any) -> None:
        self.replies_text.append(text)


class _FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id


class _FakeUpdate:
    def __init__(self, chat_id: int, voice_obj: Any) -> None:
        self.effective_chat = _FakeChat(chat_id)
        self.effective_message = _FakeMessage(voice_obj)


class _FakeVoice:
    def __init__(
        self,
        file_id: str = "AAA-VOICE-FILE-ID",
        mime_type: str = "audio/ogg",
        file_size: int = 12_345,
    ) -> None:
        self.file_id = file_id
        self.mime_type = mime_type
        self.file_size = file_size


@pytest.mark.asyncio
async def test_handler_happy_path_full_wiring(
    bot_config: BotConfig, conv_store: ConversationStore, paired_chat: int
) -> None:
    fake_anthropic = FakeAnthropic(
        [
            _Resp(
                stop_reason="end_turn",
                content=[_Block(type="text", text="Got 1 chiller RFI on your plate.")],
            )
        ]
    )
    llm = ConversationalLLM(fake_anthropic)
    whisper = FakeWhisper(available=True)

    bot = _FakeTelegramBot(voice_bytes=b"\x00\x01\x02-ogg-payload")
    app = _FakeApplication(
        bot=bot,
        bot_data={
            "api": _FakeAPI(),
            "config": bot_config,
            "llm": llm,
            "conv_store": conv_store,
            "dedup_store": get_dedup_store(),
            "whisper": whisper,
        },
    )
    ctx = _FakeContext(app)
    update = _FakeUpdate(paired_chat, _FakeVoice())

    await voice.handle_voice_message(update, ctx)

    msg = update.effective_message
    # Ack first, then the actual answer.
    assert msg.replies_text == [voice.ACK_REPLY]
    assert len(msg.replies_markdown) == 1
    assert msg.replies_markdown[0][0] == "Got 1 chiller RFI on your plate."
    # Whisper got the bytes we downloaded.
    assert whisper.transcribe_calls[0]["audio"] == b"\x00\x01\x02-ogg-payload"
    # And we asked Telegram for that exact file_id.
    assert bot.get_file_calls == ["AAA-VOICE-FILE-ID"]


@pytest.mark.asyncio
async def test_handler_unpaired_short_circuits_before_download(
    bot_config: BotConfig, conv_store: ConversationStore
) -> None:
    fake_anthropic = FakeAnthropic([])
    llm = ConversationalLLM(fake_anthropic)
    whisper = FakeWhisper(available=True)
    bot = _FakeTelegramBot(voice_bytes=b"shouldnt-be-downloaded")

    app = _FakeApplication(
        bot=bot,
        bot_data={
            "api": _FakeAPI(),
            "config": bot_config,
            "llm": llm,
            "conv_store": conv_store,
            "dedup_store": get_dedup_store(),
            "whisper": whisper,
        },
    )
    ctx = _FakeContext(app)
    update = _FakeUpdate(8675309, _FakeVoice())  # unpaired

    await voice.handle_voice_message(update, ctx)

    msg = update.effective_message
    assert msg.replies_markdown[0][0] == nl.UNPAIRED_REPLY
    # CRITICAL: we never asked Telegram to download the file for an
    # unpaired chat. That prevents wasted CDN bandwidth and avoids
    # holding the audio bytes in memory for unauthorised chats.
    assert bot.get_file_calls == []
    assert whisper.transcribe_calls == []


@pytest.mark.asyncio
async def test_handler_no_api_key_replies_with_refusal(
    bot_config: BotConfig, conv_store: ConversationStore, paired_chat: int
) -> None:
    fake_anthropic = FakeAnthropic([])
    llm = ConversationalLLM(fake_anthropic)
    whisper = FakeWhisper(available=False)
    bot = _FakeTelegramBot(voice_bytes=b"shouldnt-download")

    app = _FakeApplication(
        bot=bot,
        bot_data={
            "api": _FakeAPI(),
            "config": bot_config,
            "llm": llm,
            "conv_store": conv_store,
            "dedup_store": get_dedup_store(),
            "whisper": whisper,
        },
    )
    ctx = _FakeContext(app)
    update = _FakeUpdate(paired_chat, _FakeVoice())

    await voice.handle_voice_message(update, ctx)

    msg = update.effective_message
    assert msg.replies_markdown[0][0] == voice.WHISPER_UNCONFIGURED_REPLY
    assert bot.get_file_calls == []  # no download attempt


@pytest.mark.asyncio
async def test_handler_empty_transcript(
    bot_config: BotConfig, conv_store: ConversationStore, paired_chat: int
) -> None:
    fake_anthropic = FakeAnthropic([])  # never called — empty transcript path
    llm = ConversationalLLM(fake_anthropic)
    whisper = FakeWhisper(
        available=True,
        result=TranscriptionResult(text="", duration_sec=1.0, language="english"),
    )
    bot = _FakeTelegramBot(voice_bytes=b"silence")

    app = _FakeApplication(
        bot=bot,
        bot_data={
            "api": _FakeAPI(),
            "config": bot_config,
            "llm": llm,
            "conv_store": conv_store,
            "dedup_store": get_dedup_store(),
            "whisper": whisper,
        },
    )
    ctx = _FakeContext(app)
    update = _FakeUpdate(paired_chat, _FakeVoice())

    await voice.handle_voice_message(update, ctx)

    msg = update.effective_message
    # Ack still went out; then the "couldn't make out" message landed via
    # markdown reply.
    assert msg.replies_text == [voice.ACK_REPLY]
    assert any(
        r[0] == voice.EMPTY_TRANSCRIPT_REPLY for r in msg.replies_markdown
    )


@pytest.mark.asyncio
async def test_handler_oversize_voice_short_circuits(
    bot_config: BotConfig, conv_store: ConversationStore, paired_chat: int
) -> None:
    fake_anthropic = FakeAnthropic([])
    llm = ConversationalLLM(fake_anthropic)
    whisper = FakeWhisper(available=True)
    bot = _FakeTelegramBot(voice_bytes=b"too-big")

    app = _FakeApplication(
        bot=bot,
        bot_data={
            "api": _FakeAPI(),
            "config": bot_config,
            "llm": llm,
            "conv_store": conv_store,
            "dedup_store": get_dedup_store(),
            "whisper": whisper,
        },
    )
    ctx = _FakeContext(app)
    update = _FakeUpdate(
        paired_chat,
        _FakeVoice(file_size=26 * 1024 * 1024),  # > 25 MB cap
    )

    await voice.handle_voice_message(update, ctx)

    msg = update.effective_message
    assert any(r[0] == voice.TOO_LARGE_REPLY for r in msg.replies_markdown)
    assert bot.get_file_calls == []
