"""Collect recent emails across one or more Gmail accounts.

Two-step per the Gmail API: messages.list returns only {id, threadId}, so we
follow with messages.get(format="metadata") to pull headers + snippet cheaply.
"""
from __future__ import annotations

import logging

from ..config import Account, CollectConfig
from ..google_auth import get_service
from ..models import EmailItem

log = logging.getLogger(__name__)

_METADATA_HEADERS = ["From", "Subject", "Date"]


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _compose_query(base: str, email_filter: str) -> str:
    """Combine a base Gmail query with the relevance filter (either may be empty)."""
    return " ".join(part for part in (base.strip(), email_filter.strip()) if part)


def collect_for_account(label: str, query: str, max_results: int) -> list[EmailItem]:
    """Fetch up to `max_results` messages matching `query` for one account."""
    service = get_service(label, "gmail", "v1")
    listed = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    messages = listed.get("messages", [])
    items: list[EmailItem] = []
    for msg in messages:
        detail = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=msg["id"],
                format="metadata",
                metadataHeaders=_METADATA_HEADERS,
            )
            .execute()
        )
        headers = detail.get("payload", {}).get("headers", [])
        items.append(
            EmailItem(
                account=label,
                sender=_header(headers, "From"),
                subject=_header(headers, "Subject"),
                snippet=detail.get("snippet", ""),
                received_at=_header(headers, "Date"),
            )
        )
    return items


def collect(
    accounts: list[Account],
    collect_cfg: CollectConfig,
    warnings: list[str],
    query: str | None = None,
    max_results: int | None = None,
) -> list[EmailItem]:
    """Fetch emails across all accounts; failures are recorded, not fatal.

    When `query` is None, the daily query (`email_query` + `email_filter`) is used.
    The `seed` backfill passes an explicit per-day query (already filter-composed).
    """
    effective_query = query or _compose_query(
        collect_cfg.email_query, collect_cfg.email_filter
    )
    cap = max_results if max_results is not None else collect_cfg.max_emails_per_account
    all_items: list[EmailItem] = []
    for acct in accounts:
        try:
            items = collect_for_account(acct.label, effective_query, cap)
            log.info("Gmail[%s]: %d messages", acct.label, len(items))
            all_items.extend(items)
        except Exception as exc:  # noqa: BLE001 — continue-on-partial-failure
            msg = f"Gmail collection failed for account '{acct.label}': {exc}"
            log.warning(msg)
            warnings.append(msg)
    return all_items
