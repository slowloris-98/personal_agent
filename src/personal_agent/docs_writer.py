"""Write the day's plan into that week's Google Doc, formatted, one page per day.

The agent owns a Drive folder (by name) and auto-creates a new Doc in it each ISO
week. Each run prepends the day at the top of the current week's Doc with native
Docs formatting (headings, bold, bullets) and a page break so every day gets its
own page. See `markdown_to_docs` for the Markdown -> Docs request translation.

Everything uses the narrow `drive.file` scope, which only exposes files this app
created — hence the agent creates and owns the folder rather than pointing at a
pre-existing one.
"""
from __future__ import annotations

import logging
from datetime import date as date_cls

from . import markdown_to_docs
from .google_auth import get_service

log = logging.getLogger(__name__)

_DOC_MIME = "application/vnd.google-apps.document"
_FOLDER_MIME = "application/vnd.google-apps.folder"


def _escape(value: str) -> str:
    """Escape a value for use inside a Drive `q` string literal."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _week_title(date: str) -> str:
    """Deterministic Doc title for the ISO week containing `date` (YYYY-MM-DD)."""
    iso = date_cls.fromisoformat(date).isocalendar()
    return f"Daily Plans — {iso[0]}-W{iso[1]:02d}"


def _find_file(drive, query: str) -> str | None:
    files = (
        drive.files()
        .list(q=query, spaces="drive", fields="files(id, name)")
        .execute()
        .get("files", [])
    )
    return files[0]["id"] if files else None


def get_or_create_folder(drive, folder_name: str) -> str:
    """Return the id of the agent's plan folder, creating it if it doesn't exist.

    `drive.file` only lists files this app created, so this finds the folder only
    if the agent made it — which is exactly what we want.
    """
    query = (
        f"name = '{_escape(folder_name)}' and mimeType = '{_FOLDER_MIME}' "
        f"and trashed = false"
    )
    existing = _find_file(drive, query)
    if existing:
        return existing
    created = (
        drive.files()
        .create(body={"name": folder_name, "mimeType": _FOLDER_MIME}, fields="id")
        .execute()
    )
    log.info("Created plan folder '%s' (%s)", folder_name, created["id"])
    return created["id"]


def get_or_create_week_doc(label: str, folder_name: str, date: str) -> str:
    """Return the id of this week's plan Doc, creating the folder/Doc as needed."""
    if not folder_name:
        raise ValueError("output.folder_name is not set in config.yaml.")

    drive = get_service(label, "drive", "v3")
    folder_id = get_or_create_folder(drive, folder_name)

    title = _week_title(date)
    query = (
        f"name = '{_escape(title)}' and '{folder_id}' in parents "
        f"and mimeType = '{_DOC_MIME}' and trashed = false"
    )
    existing = _find_file(drive, query)
    if existing:
        return existing

    created = (
        drive.files()
        .create(
            body={"name": title, "mimeType": _DOC_MIME, "parents": [folder_id]},
            fields="id",
        )
        .execute()
    )
    log.info("Created weekly plan doc '%s' (%s)", title, created["id"])
    return created["id"]


def _has_content(docs_service, doc_id: str) -> bool:
    """True if the doc already has body content below (i.e. we need a page break)."""
    doc = docs_service.documents().get(documentId=doc_id, fields="body/content").execute()
    content = doc.get("body", {}).get("content", [])
    # An empty doc is a single empty paragraph ending at index 2.
    return bool(content) and content[-1].get("endIndex", 1) > 2


def prepend_plan(primary_label: str, folder_name: str, date: str, plan_markdown: str) -> None:
    """Insert a dated, formatted plan block at the top of this week's Doc.

    Newest plan ends up on top; earlier days sit below on their own pages.
    """
    doc_id = get_or_create_week_doc(primary_label, folder_name, date)
    docs = get_service(primary_label, "docs", "v1")

    add_page_break = _has_content(docs, doc_id)
    requests = markdown_to_docs.build_day_requests(
        date=date,
        plan_markdown=plan_markdown,
        insert_index=1,  # start of the document body
        add_page_break=add_page_break,
    )
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    log.info("Prepended plan for %s to weekly doc %s", date, doc_id)
