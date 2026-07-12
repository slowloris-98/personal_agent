"""Compose an answer to a user's question from the store, via a switchable LLM.

Read-only: the model answers strictly from the retrieved context (today's plan,
calendar, tasks, recent emails) plus recent conversation history. It never acts on
the user's behalf. The provider is injected, so the caller (the Telegram bot) picks
anthropic / openai / ollama from config and can switch at runtime.
"""
from __future__ import annotations

from ..llm.base import LLMProvider
from .. import store
from .retrieval import build_context

_SYSTEM_PROMPT = """\
You are the user's personal daily-planning assistant, reachable over a messaging \
app. Answer their question using ONLY the context provided below — their latest \
daily plan, calendar events, open tasks, and recent emails.

Rules:
- If the answer isn't supported by the context, say so plainly; do not invent \
events, emails, or tasks.
- Be concise and direct — this is a chat, not a document. A few sentences or a \
short bulleted list is ideal.
- You are read-only: you cannot send emails, create tasks, or change anything. If \
asked to, explain that you can only look things up.
- Reply in lightweight GitHub-flavored Markdown (bold, bullets) that reads well on \
a phone. Avoid tables and long headings.\
"""

_HISTORY_LIMIT = 6  # prior turns (3 exchanges) carried for follow-ups


def _format_history(turns: list[dict]) -> str:
    if not turns:
        return ""
    lines = ["=== RECENT CONVERSATION ==="]
    for t in turns:
        who = "User" if t["role"] == "user" else "You"
        lines.append(f"{who}: {t['content']}")
    return "\n".join(lines) + "\n\n"


def build_user_prompt(conn, chat_id: str, question: str) -> str:
    """The full user-turn prompt: history + retrieved context + the question."""
    history = _format_history(store.recent_turns(conn, chat_id, n=_HISTORY_LIMIT))
    context = build_context(conn, question)
    return (
        f"{history}{context}\n\n"
        f"=== USER QUESTION ===\n{question}"
    )


def answer_question(conn, provider: LLMProvider, chat_id: str, question: str) -> str:
    """Answer `question` for `chat_id` and persist both turns to history."""
    user_prompt = build_user_prompt(conn, chat_id, question)
    reply = provider.generate(_SYSTEM_PROMPT, user_prompt)
    store.append_turn(conn, chat_id, "user", question)
    store.append_turn(conn, chat_id, "assistant", reply)
    return reply
