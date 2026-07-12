"""Assemble the context block the responder LLM answers from.

Pulls the latest daily plan (plus the calendar/tasks captured in its bundle) and
the emails most relevant to the user's question via the store's FTS index, then
renders them into a compact plain-text block — the same spirit as
`planner.build_user_prompt`, but reading from the phone-local store.
"""
from __future__ import annotations

import json

from .. import store


def _render_events(events: list[dict]) -> list[str]:
    lines = ["=== TODAY'S CALENDAR EVENTS ==="]
    if not events:
        lines.append("(none)")
        return lines
    for ev in events:
        when = "all day" if ev.get("all_day") else f"{ev.get('start', '')} → {ev.get('end', '')}"
        loc = f" @ {ev['location']}" if ev.get("location") else ""
        lines.append(f"- {when}: {ev.get('summary', '')}{loc}")
    return lines


def _render_tasks(tasks: list[dict]) -> list[str]:
    lines = ["=== OPEN TASKS ==="]
    if not tasks:
        lines.append("(none)")
        return lines
    for t in tasks:
        due = f" (due {t['due']})" if t.get("due") else ""
        note = f" — {t['notes']}" if t.get("notes") else ""
        lines.append(f"- {t.get('title', '')}{due}{note}")
    return lines


def _render_emails(emails: list[dict]) -> list[str]:
    lines = ["=== RELEVANT EMAILS ==="]
    if not emails:
        lines.append("(none)")
        return lines
    for e in emails:
        lines.append(
            f"- [{e.get('account', '')}] {e.get('received_at', '')} | "
            f"From: {e.get('sender', '')} | Subject: {e.get('subject', '')}\n"
            f"    {e.get('snippet', '')}"
        )
    return lines


def build_context(conn, user_msg: str, email_limit: int = 8) -> str:
    """Build the retrieval context for `user_msg` from the store."""
    lines: list[str] = []

    plan = store.latest_plan(conn)
    if plan:
        lines.append(f"=== LATEST DAILY PLAN ({plan['date']}) ===")
        lines.append(plan["plan_markdown"])
        lines.append("")
        bundle = {}
        if plan.get("bundle_json"):
            try:
                bundle = json.loads(plan["bundle_json"]) or {}
            except json.JSONDecodeError:
                bundle = {}
        lines += _render_events(bundle.get("events", []))
        lines.append("")
        lines += _render_tasks(bundle.get("tasks", []))
        lines.append("")
    else:
        lines.append("(no daily plan has been recorded yet)")
        lines.append("")

    emails = store.search_emails(conn, user_msg, limit=email_limit)
    lines += _render_emails(emails)

    return "\n".join(lines)
