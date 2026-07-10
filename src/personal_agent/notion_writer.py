"""Write the day's plan into Notion: root page -> weekly subpage -> day subpage.

Structure created under the "Daily Planning" page you share with the integration:

    Daily Planning              (root_page_id, from config)
    └── Week 2026-W28           (one subpage per ISO week)
        ├── 2026-07-06 Monday   (one subpage per day; plan Markdown dumped in)
        └── ...

Notion's Markdown Content API lets us POST the LLM's Markdown string directly as
the page body (the `markdown` field) — no block translation, unlike the Google
Docs path. See `docs_writer` for the equivalent Google implementation.

This path is *write-only*: we never read pages back or use Notion's search API.
To avoid creating a duplicate weekly/day page on each run, page ids are cached in
a local state file (`credentials/notion_state.json`) keyed by week and date. A
re-run for the same day replaces that day page's content instead of adding a new
page.
"""
from __future__ import annotations

import json
import logging
from datetime import date as date_cls

import requests

from .config import CREDENTIALS_DIR

log = logging.getLogger(__name__)

_API_ROOT = "https://api.notion.com/v1"
# Version that enables the Markdown Content API (create/update pages via Markdown).
_NOTION_VERSION = "2026-03-11"
_TIMEOUT = 30  # seconds

_STATE_PATH = CREDENTIALS_DIR / "notion_state.json"


def _week_label(date: str) -> str:
    """Deterministic weekly-page title for the ISO week containing `date`."""
    iso = date_cls.fromisoformat(date).isocalendar()
    return f"Week {iso[0]}-W{iso[1]:02d}"


def _day_title(date: str) -> str:
    """Day-page title, e.g. '2026-07-06 Monday'."""
    return f"{date} {date_cls.fromisoformat(date).strftime('%A')}"


def _load_state() -> dict:
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Could not read Notion state file %s; starting fresh", _STATE_PATH)
        return {}


def _save_state(state: dict) -> None:
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _post(token: str, path: str, body: dict) -> dict:
    resp = requests.post(
        f"{_API_ROOT}{path}", headers=_headers(token), json=body, timeout=_TIMEOUT
    )
    if not resp.ok:
        raise RuntimeError(f"Notion POST {path} failed ({resp.status_code}): {resp.text}")
    return resp.json()


def _patch(token: str, path: str, body: dict) -> dict:
    resp = requests.patch(
        f"{_API_ROOT}{path}", headers=_headers(token), json=body, timeout=_TIMEOUT
    )
    if not resp.ok:
        raise RuntimeError(f"Notion PATCH {path} failed ({resp.status_code}): {resp.text}")
    return resp.json()


def _create_page(token: str, parent_id: str, title: str, markdown: str | None = None) -> str:
    """Create a subpage under `parent_id`; optionally dump `markdown` as its body."""
    body: dict = {
        "parent": {"page_id": parent_id},
        "properties": {"title": {"title": [{"text": {"content": title}}]}},
    }
    if markdown is not None:
        body["markdown"] = markdown
    return _post(token, "/pages", body)["id"]


def _replace_page_markdown(token: str, page_id: str, markdown: str) -> None:
    """Replace a page's entire body with `markdown` (used on same-day re-runs)."""
    _patch(
        token,
        f"/pages/{page_id}/markdown",
        {"type": "replace_content", "replace_content": {"new_str": markdown}},
    )


def _get_or_create_week_page(token: str, root_page_id: str, week: str, state: dict) -> str:
    """Return the cached weekly page id, creating it under the root if needed."""
    entry = state.get(week)
    if entry and entry.get("page_id"):
        return entry["page_id"]
    page_id = _create_page(token, root_page_id, week)
    state[week] = {"page_id": page_id, "days": {}}
    log.info("Created Notion weekly page '%s' (%s)", week, page_id)
    return page_id


def write_plan(token: str, root_page_id: str, date: str, plan_markdown: str) -> None:
    """Write the day's plan into Notion under root -> week -> day.

    Creates the weekly page and day page as needed; a re-run for the same day
    replaces that day page's content rather than adding a duplicate.
    """
    if not token:
        raise ValueError("NOTION_API_KEY is not set in .env.")
    if not root_page_id:
        raise ValueError("output.notion_root_page_id is not set in config.yaml.")

    state = _load_state()
    week = _week_label(date)
    week_page_id = _get_or_create_week_page(token, root_page_id, week, state)

    days = state[week].setdefault("days", {})
    existing_day = days.get(date)
    if existing_day:
        _replace_page_markdown(token, existing_day, plan_markdown)
        log.info("Replaced Notion day page for %s (%s)", date, existing_day)
    else:
        day_page_id = _create_page(token, week_page_id, _day_title(date), plan_markdown)
        days[date] = day_page_id
        log.info("Created Notion day page for %s (%s)", date, day_page_id)

    _save_state(state)
