"""Collect open Google Tasks from the primary account's default task list."""
from __future__ import annotations

import logging

from ..google_auth import get_service
from ..models import TaskItem

log = logging.getLogger(__name__)


def collect(primary_label: str, warnings: list[str]) -> list[TaskItem]:
    try:
        service = get_service(primary_label, "tasks", "v1")
        # "@default" is the special id for the user's default task list.
        resp = (
            service.tasks()
            .list(
                tasklist="@default",
                showCompleted=False,  # API default is True — must opt out
                maxResults=100,
            )
            .execute()
        )
        tasks: list[TaskItem] = []
        for t in resp.get("items", []):
            # Defensive: skip anything still marked completed.
            if t.get("status") == "completed":
                continue
            tasks.append(
                TaskItem(
                    title=t.get("title", "(untitled task)"),
                    due=t.get("due", ""),
                    notes=t.get("notes", ""),
                )
            )
        log.info("Tasks[%s]: %d open tasks", primary_label, len(tasks))
        return tasks
    except Exception as exc:  # noqa: BLE001
        msg = f"Tasks collection failed: {exc}"
        log.warning(msg)
        warnings.append(msg)
        return []
