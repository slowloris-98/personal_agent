"""Write the day's plan into Google Docs: one Doc per day, native Markdown import.

Each run hands the LLM's plan Markdown to Drive's native Markdown importer, which
creates a fully-formatted Google Doc (headings, bold, bullets, tables, links) — no
bespoke Markdown->Docs translation on our side. The daily Doc lands in a Drive
folder: by default one the agent creates and owns (by name), or a specific folder
you point at with `folder_id`.

    Daily Plans/                 (folder_name, created and owned by the agent)
    ├── 2026-07-06 — Daily Plan  (one Doc per day; a re-run replaces that day's Doc)
    └── ...

Everything uses the narrow `drive.file` scope, which only exposes files this app
created. That's why the default folder is one the agent makes rather than a
pre-existing one; a configured `folder_id` only works if the app can access it.
"""
from __future__ import annotations

import logging

from googleapiclient.http import MediaInMemoryUpload

from .google_auth import get_service

log = logging.getLogger(__name__)

_DOC_MIME = "application/vnd.google-apps.document"
_FOLDER_MIME = "application/vnd.google-apps.folder"
_MARKDOWN_MIME = "text/markdown"


def _escape(value: str) -> str:
    """Escape a value for use inside a Drive `q` string literal."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _daily_title(date: str) -> str:
    """Deterministic Doc title for a day's plan, e.g. '2026-07-06 — Daily Plan'."""
    return f"{date} — Daily Plan"


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


def _resolve_folder(drive, folder_id: str, folder_name: str) -> str:
    """Return the target folder id: an explicit `folder_id`, else one by name.

    A configured `folder_id` wins; otherwise the agent creates/owns `folder_name`.
    """
    if folder_id:
        return folder_id
    if not folder_name:
        raise ValueError(
            "Set output.folder_id or output.folder_name in config.yaml for google_docs."
        )
    return get_or_create_folder(drive, folder_name)


def write_day_doc(
    label: str, folder_id: str, folder_name: str, date: str, plan_markdown: str
) -> str:
    """Create (or replace) the day's plan Doc from Markdown via Drive's importer.

    Uploads the plan Markdown with source mimeType text/markdown and target Google
    Doc mimeType, so Drive converts it natively. A re-run for the same day replaces
    that day's Doc content instead of creating a duplicate. Returns the Doc id.
    """
    drive = get_service(label, "drive", "v3")
    folder = _resolve_folder(drive, folder_id, folder_name)

    title = _daily_title(date)
    media = MediaInMemoryUpload(
        plan_markdown.encode("utf-8"), mimetype=_MARKDOWN_MIME, resumable=False
    )

    query = (
        f"name = '{_escape(title)}' and '{folder}' in parents "
        f"and mimeType = '{_DOC_MIME}' and trashed = false"
    )
    existing = _find_file(drive, query)
    if existing:
        drive.files().update(fileId=existing, media_body=media).execute()
        log.info("Replaced plan doc '%s' (%s)", title, existing)
        return existing

    created = (
        drive.files()
        .create(
            body={"name": title, "mimeType": _DOC_MIME, "parents": [folder]},
            media_body=media,
            fields="id",
        )
        .execute()
    )
    log.info("Created plan doc '%s' (%s)", title, created["id"])
    return created["id"]
