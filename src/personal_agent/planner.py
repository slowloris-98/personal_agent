"""Turn a ContextBundle into a Markdown day plan via an LLM provider."""
from __future__ import annotations

from .llm.base import LLMProvider
from .models import ContextBundle

_SYSTEM_PROMPT_TEMPLATE = """\
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

Output GitHub-flavored Markdown with exactly these sections, and nothing before them.
Use "###" headings, "-" bullets, and "**bold**" for emphasis.{tables_note}
- "### Top priorities" — 3-5 bullets, most important first.
- "### Time-blocked schedule" — {schedule_hint}
- "### Action items from email" — bullets, each noting the source account.
- "### Watch / urgent" — anything needing attention today; write "Nothing urgent." if none.

Be concise and concrete. Do not invent events or emails that were not provided.\
"""

_NO_TABLES_NOTE = " Do NOT use Markdown tables (they don't render in the output document)."
_TABLES_OK_NOTE = " You may use Markdown tables where they make the plan clearer."

_SCHEDULE_HINT_BULLETS = (
    "a bulleted list mapping time ranges to activities,\n"
    '  anchored around the real calendar events, e.g. "- 09:00–10:00 — Deep work: <task>".'
)
_SCHEDULE_HINT_TABLE = (
    "a Markdown table (or bulleted list) mapping time\n"
    "  ranges to activities, anchored around the real calendar events."
)


def build_system_prompt(allow_tables: bool) -> str:
    """The system prompt, allowing or forbidding Markdown tables by output target."""
    return _SYSTEM_PROMPT_TEMPLATE.format(
        tables_note=_TABLES_OK_NOTE if allow_tables else _NO_TABLES_NOTE,
        schedule_hint=_SCHEDULE_HINT_TABLE if allow_tables else _SCHEDULE_HINT_BULLETS,
    )


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


def generate_plan(
    bundle: ContextBundle, provider: LLMProvider, allow_tables: bool = False
) -> str:
    """Build the prompt, call the LLM, return Markdown plan text.

    `allow_tables` lets the LLM use Markdown tables — enabled for output targets
    that render them (Notion), off for Google Docs.
    """
    system_prompt = build_system_prompt(allow_tables)
    user_prompt = build_user_prompt(bundle)
    return provider.generate(system_prompt, user_prompt)
