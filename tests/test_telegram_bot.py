import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from personal_agent import store  # noqa: E402
from personal_agent.config import Config, ResponderConfig  # noqa: E402
from personal_agent.responder import telegram_bot as tb  # noqa: E402


class FakeProvider:
    def __init__(self, reply="answer text"):
        self.reply, self.calls = reply, []

    def generate(self, system, user):
        self.calls.append((system, user))
        return self.reply


@pytest.fixture
def state():
    conn = store.init_db(":memory:")
    store.upsert_plan(conn, "2026-07-11", "### Plan\n- do things", None)
    st = tb.BotState(
        conn=conn,
        config=Config(responder=ResponderConfig(provider="anthropic", model="m")),
        provider=FakeProvider(),
        provider_name="anthropic",
        model="m",
        allowed={111},
    )
    yield st
    conn.close()


def test_unauthorized_chat_is_ignored(state):
    assert tb.handle_message(state, 999, "hello") is None


def test_help_command(state):
    reply = tb.handle_message(state, 111, "/help")
    assert "read-only" in reply.lower()
    assert "/model" in reply


def test_normal_question_answered_and_persisted(state):
    reply = tb.handle_message(state, 111, "what's my plan?")
    assert reply == "answer text"
    assert state.provider.calls  # provider was invoked
    turns = store.recent_turns(state.conn, "111", n=10)
    assert [t["role"] for t in turns] == ["user", "assistant"]


def test_model_command_reports_current(state):
    reply = tb.handle_message(state, 111, "/model")
    assert "anthropic" in reply and "m" in reply


def test_model_command_switches_provider(state):
    reply = tb.handle_message(state, 111, "/model ollama llama3")
    assert "ollama" in reply
    assert state.provider_name == "ollama"
    assert state.model == "llama3"


def test_model_command_rejects_unknown(state):
    reply = tb.handle_message(state, 111, "/model banana")
    assert "Unknown provider" in reply
    assert state.provider_name == "anthropic"  # unchanged


def test_answer_error_is_caught(state, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("llm down")
    monkeypatch.setattr(tb, "answer_question", boom)
    reply = tb.handle_message(state, 111, "anything")
    assert "error" in reply.lower()


def test_empty_allowlist_allows_everyone():
    conn = store.init_db(":memory:")
    st = tb.BotState(conn, Config(), FakeProvider(), "anthropic", "m", allowed=set())
    assert tb.handle_message(st, 12345, "/help") is not None
    conn.close()


# ---- TelegramClient message splitting / sending ----

class FakeSession:
    def __init__(self):
        self.posts = []

    def post(self, url, json=None, timeout=None):
        self.posts.append(json)
        return _Ok()


class _Ok:
    def raise_for_status(self):
        pass


def test_split_short_message_single_chunk():
    assert tb._split("hello", 4000) == ["hello"]


def test_split_long_message_respects_limit():
    text = "\n".join(f"line {i}" for i in range(2000))
    chunks = tb._split(text, 100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks) == text


def test_send_message_chunks_long_text():
    session = FakeSession()
    client = tb.TelegramClient("tok", session=session)
    client.send_message(111, "x" * 9000)
    assert len(session.posts) == 3               # 9000 / 4000 -> 3 chunks
    assert all(p["chat_id"] == 111 for p in session.posts)
