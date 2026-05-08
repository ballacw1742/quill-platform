"""Tests for ConversationStore (Phase B, Commit 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from quill_bot.conversation import (
    DEFAULT_KEEP,
    ConversationStore,
    Message,
    reset_store_for_tests,
)


@pytest.fixture
def store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(tmp_path / "conv.db")


def test_init_creates_db_and_schema(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "conv.db"
    s = ConversationStore(db)
    assert db.exists()
    # Schema exists — empty history should not raise.
    assert s.history(123) == []


def test_append_and_history_user_assistant(store: ConversationStore) -> None:
    store.append(1, "user", content="hi")
    store.append(1, "assistant", content="hello")
    hist = store.history(1)
    assert len(hist) == 2
    assert hist[0].role == "user"
    assert hist[0].content == "hi"
    assert hist[1].role == "assistant"
    assert hist[1].content == "hello"
    # ISO timestamps populated
    assert "T" in hist[0].created_at


def test_history_isolates_per_chat(store: ConversationStore) -> None:
    store.append(1, "user", content="from-1")
    store.append(2, "user", content="from-2")
    assert [m.content for m in store.history(1)] == ["from-1"]
    assert [m.content for m in store.history(2)] == ["from-2"]


def test_append_assistant_with_tool_calls_round_trips(store: ConversationStore) -> None:
    tcs = [
        {"id": "tc-1", "name": "search_approvals", "input": {"query": "chiller"}},
    ]
    store.append(1, "assistant", content="checking", tool_calls=tcs)
    store.append(1, "tool", content='{"items":[]}', tool_call_id="tc-1")
    hist = store.history(1)
    assert hist[0].tool_calls == tcs
    assert hist[1].role == "tool"
    assert hist[1].tool_call_id == "tc-1"


def test_history_max_messages_returns_most_recent(store: ConversationStore) -> None:
    for i in range(10):
        store.append(7, "user", content=f"m{i}")
    hist = store.history(7, max_messages=3)
    assert [m.content for m in hist] == ["m7", "m8", "m9"]


def test_history_default_keep_is_24(store: ConversationStore) -> None:
    assert DEFAULT_KEEP == 24
    for i in range(40):
        store.append(9, "user", content=f"m{i}")
    hist = store.history(9)
    assert len(hist) == 24
    # Most recent kept
    assert hist[-1].content == "m39"


def test_trim_keeps_most_recent_n(store: ConversationStore) -> None:
    for i in range(30):
        store.append(5, "user", content=f"m{i}")
    deleted = store.trim(5, keep=10)
    assert deleted == 20
    hist = store.history(5, max_messages=100)
    assert len(hist) == 10
    assert [m.content for m in hist] == [f"m{i}" for i in range(20, 30)]


def test_trim_no_op_when_under_threshold(store: ConversationStore) -> None:
    for i in range(3):
        store.append(5, "user", content=f"m{i}")
    assert store.trim(5, keep=10) == 0
    assert store.count(5) == 3


def test_reset_clears_only_that_chat(store: ConversationStore) -> None:
    store.append(1, "user", content="a")
    store.append(2, "user", content="b")
    deleted = store.reset(1)
    assert deleted == 1
    assert store.history(1) == []
    assert len(store.history(2)) == 1


def test_message_to_anthropic_user() -> None:
    m = Message(chat_id=1, role="user", content="hello")
    assert m.to_anthropic() == {"role": "user", "content": "hello"}


def test_message_to_anthropic_assistant_text_only() -> None:
    m = Message(chat_id=1, role="assistant", content="hi")
    out = m.to_anthropic()
    assert out["role"] == "assistant"
    assert out["content"] == [{"type": "text", "text": "hi"}]


def test_message_to_anthropic_assistant_with_tool_calls() -> None:
    tcs = [{"id": "tc-1", "name": "get_health", "input": {}}]
    m = Message(chat_id=1, role="assistant", content="checking", tool_calls=tcs)
    out = m.to_anthropic()
    assert out["content"][0] == {"type": "text", "text": "checking"}
    assert out["content"][1] == {
        "type": "tool_use",
        "id": "tc-1",
        "name": "get_health",
        "input": {},
    }


def test_message_to_anthropic_tool_result_is_user_role() -> None:
    m = Message(chat_id=1, role="tool", content='{"ok":true}', tool_call_id="tc-1")
    out = m.to_anthropic()
    assert out["role"] == "user"
    assert out["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "tc-1",
        "content": '{"ok":true}',
    }


def test_reset_store_for_tests_swaps_singleton(tmp_path: Path) -> None:
    s = reset_store_for_tests(tmp_path / "swap.db")
    s.append(1, "user", content="z")
    from quill_bot.conversation import get_store
    assert get_store() is s
    assert get_store().history(1)[0].content == "z"
