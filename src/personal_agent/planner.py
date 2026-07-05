"""Turn a ContextBundle into a Markdown day plan via an LLM provider."""
from __future__ import annotations

from .llm.base import LLMProvider
from .models import ContextBundle

SYSTEM_PROMPT = """\
You are a personal executive-assistant agent. Given a person's emails from the \
last 24 hours (across several accounts), today's calendar events, and their open \
to-do tasks, produce a focused, realistic plan for the day.

Do this:
1. Extract concrete action items from the emails (things that need a reply or a task).
   Ignore newsletters, promotions, and pure notifications.
2. Reconcile against the calendar: schedule work into the gaps between meetings; do
   not double-book. Respect existing events.
3. Merge in the open tasks, prioritizing by due date and importance.
4. Flag anything genuinely urgent or time-sensitive.

Output GitHub-flavored Markdown with exactly these sections, and nothing before them:
- "### Top priorities" — 3-5 bullets, most important first.
- "### Time-blocked schedule" — a table or list mapping time ranges to activities,
  anchored around the real calendar events.
- "### Action items from email" — bullets, each noting the source account.
- "### Watch / urgent" — anything needing attention today; write "Nothing urgent." if none.

Be concise and concrete. Do not invent events or emails that were not provided.\
"""


def build_user_prompt(bundle: ContextBundle) -> str:
    lines: list[str] = []
    lines.append(f"DATE: {bundle.date} ({bundle.timezone})")
    lines.append("")

    lines.append("=== TODAY'S CALENDAR EVENTS ===")
    if bundle.events:
        for ev in bundle.events:
            when = "all day" if ev.all_day else f"{ev.start} → {ev.end}"
            loc = f" @ {ev.location}" if ev.location else ""
            lines.append(f"- {when}: {ev.summary}{loc}")
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("=== OPEN TASKS ===")
    if bundle.tasks:
        for t in bundle.tasks:
            due = f" (due {t.due})" if t.due else ""
            note = f" — {t.notes}" if t.notes else ""
            lines.append(f"- {t.title}{due}{note}")
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("=== EMAILS (last 24h) ===")
    if bundle.emails:
        for e in bundle.emails:
            lines.append(
                f"- [{e.account}] From: {e.sender} | Subject: {e.subject}\n"
                f"    {e.snippet}"
            )
    else:
        lines.append("(none)")
    lines.append("")

    if bundle.warnings:
        lines.append("=== COLLECTION WARNINGS (some data may be missing) ===")
        for w in bundle.warnings:
            lines.append(f"- {w}")
        lines.append("")

    return "\n".join(lines)


def generate_plan(bundle: ContextBundle, provider: LLMProvider) -> str:
    """Build the prompt, call the LLM, return Markdown plan text."""
    user_prompt = build_user_prompt(bundle)
    return provider.generate(SYSTEM_PROMPT, user_prompt)
