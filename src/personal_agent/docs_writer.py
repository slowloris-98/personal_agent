"""Prepend the day's plan to the top of a single rolling Google Doc."""
from __future__ import annotations

import logging

from .google_auth import get_service

log = logging.getLogger(__name__)

_DIVIDER = "\n" + ("─" * 40) + "\n\n"


def prepend_plan(primary_label: str, doc_id: str, date: str, plan_markdown: str) -> None:
    """Insert a dated plan block at the very top (index 1) of the doc.

    Newest plan ends up on top; previous days scroll below. Note: content is
    inserted as plain text (Markdown syntax is preserved literally, which stays
    perfectly readable in Docs).
    """
    if not doc_id or doc_id.startswith("PASTE_"):
        raise ValueError(
            "output.doc_id is not set in config.yaml. Create a Google Doc and paste "
            "its ID (from the URL) into config.yaml under output.doc_id."
        )

    service = get_service(primary_label, "docs", "v1")
    block = f"{date} — Daily Plan\n\n{plan_markdown.strip()}\n{_DIVIDER}"

    # index 1 is the start of the document body.
    requests = [{"insertText": {"location": {"index": 1}, "text": block}}]
    service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()
    log.info("Prepended plan for %s to doc %s", date, doc_id)
