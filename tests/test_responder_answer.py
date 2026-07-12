import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from personal_agent import store  # noqa: E402
from personal_agent.llm import get_provider  # noqa: E402
from personal_agent.llm.ollama_provider import OllamaProvider  # noqa: E402
from personal_agent.models import EmailItem  # noqa: E402
from personal_agent.responder import answer, retrieval  # noqa: E402


class FakeProvider:
    """Records the prompts it was called with and returns a canned reply."""

    def __init__(self):
        self.calls = []

    def generate(self, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        return "Here is your answer."


@pytest.fixture
def conn():
    c = store.init_db(":memory:")
    yield c
    c.close()


def _seed(conn):
    bundle = {
        "date": "2026-07-11",
        "timezone": "UTC",
        "events": [{"summary": "Dentist", "start": "10:00", "end": "10:30",
                    "location": "Clinic", "all_day": False}],
        "tasks": [{"title": "File taxes", "due": "2026-07-15", "notes": "form 16"}],
    }
    store.upsert_plan(conn, "2026-07-11", "### Top priorities\n- Ship release",
                      json.dumps(bundle))
    store.upsert_emails(conn, [
        EmailItem("Personal", "boss@x.com", "Invoice overdue", "please pay the invoice",
                  "Wed, 09 Jul 2026 10:00:00 +0000", "g1"),
        EmailItem("Work", "team@x.com", "Team lunch", "pizza on friday",
                  "Wed, 09 Jul 2026 08:00:00 +0000", "g2"),
    ])


# ---- factory registration ----

def test_factory_registers_ollama():
    p = get_provider("ollama", model="llama3", max_tokens=100)
    assert isinstance(p, OllamaProvider)
    assert p.model == "llama3"


# ---- retrieval ----

def test_build_context_includes_plan_events_tasks(conn):
    _seed(conn)
    ctx = retrieval.build_context(conn, "what's due?")
    assert "LATEST DAILY PLAN (2026-07-11)" in ctx
    assert "Ship release" in ctx
    assert "Dentist" in ctx and "@ Clinic" in ctx
    assert "File taxes" in ctx and "due 2026-07-15" in ctx


def test_build_context_email_search_is_relevant(conn):
    _seed(conn)
    ctx = retrieval.build_context(conn, "invoice")
    assert "Invoice overdue" in ctx
    # The unrelated lunch email should not surface for an 'invoice' query.
    assert "Team lunch" not in ctx


def test_build_context_handles_empty_store(conn):
    ctx = retrieval.build_context(conn, "anything")
    assert "no daily plan" in ctx
    assert "=== RELEVANT EMAILS ===" in ctx


# ---- answer ----

def test_answer_calls_provider_and_persists_turns(conn):
    _seed(conn)
    fake = FakeProvider()
    reply = answer.answer_question(conn, fake, "chat1", "is my invoice paid?")

    assert reply == "Here is your answer."
    # The prompt carried the retrieved context.
    assert "Invoice overdue" in fake.calls[0]["user"]
    assert "read-only" in fake.calls[0]["system"].lower()

    # Both turns stored for follow-up context.
    turns = store.recent_turns(conn, "chat1", n=10)
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[0]["content"] == "is my invoice paid?"
    assert turns[1]["content"] == "Here is your answer."


def test_answer_includes_recent_history(conn):
    _seed(conn)
    fake = FakeProvider()
    answer.answer_question(conn, fake, "chat1", "first question")
    answer.answer_question(conn, fake, "chat1", "follow up")

    # The second call's prompt should reference the earlier exchange.
    second_prompt = fake.calls[1]["user"]
    assert "RECENT CONVERSATION" in second_prompt
    assert "first question" in second_prompt
