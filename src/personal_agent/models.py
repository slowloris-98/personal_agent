"""Normalized data models passed from collectors to the planner."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EmailItem:
    account: str          # account label the email came from
    sender: str
    subject: str
    snippet: str
    received_at: str      # human/ISO-ish string from the Date header
    gmail_id: str = ""    # Gmail message id; stable dedup key for the responder store


@dataclass
class CalendarEvent:
    summary: str
    start: str            # RFC3339 or date string
    end: str
    location: str = ""
    all_day: bool = False


@dataclass
class TaskItem:
    title: str
    due: str = ""         # RFC3339 date, or "" if none
    notes: str = ""


@dataclass
class ContextBundle:
    """Everything the planner needs to build a day plan."""
    date: str                                   # local YYYY-MM-DD
    timezone: str
    emails: list[EmailItem] = field(default_factory=list)
    events: list[CalendarEvent] = field(default_factory=list)
    tasks: list[TaskItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # partial-failure notes
