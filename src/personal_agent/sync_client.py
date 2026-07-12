"""PC side of the responder sync: push the day's plan + emails to the phone.

Called at the end of the daily run (and by `scripts/backfill_emails`). Two jobs:

1. Always write the payload to a local `data/snapshots/<date>.json` — a durable
   second copy so the phone DB is never the only copy and re-seeding is instant.
2. Best-effort POST the same payload to the phone's `/ingest` endpoint over
   Tailscale. Failure is logged, never fatal — the daily plan has already been
   written to its output target by the time we get here.

Payload contract (also parsed by `responder/ingest_server`):

    {
      "date":   "2026-07-11",
      "plan":   "### ...markdown..."  | null,   # null for email-only backfill
      "emails": [ {account, sender, subject, snippet, received_at, gmail_id}, ... ],
      "bundle": { ...ContextBundle asdict... }   | null
    }
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import requests

from .config import DATA_DIR
from .models import ContextBundle, EmailItem

log = logging.getLogger(__name__)

_TIMEOUT = 30  # seconds
SNAPSHOT_DIR = DATA_DIR / "snapshots"


def build_payload(
    date: str,
    plan: str | None,
    emails: list[EmailItem],
    bundle: ContextBundle | None = None,
) -> dict:
    return {
        "date": date,
        "plan": plan,
        "emails": [asdict(e) for e in emails],
        "bundle": asdict(bundle) if bundle is not None else None,
    }


def save_snapshot(payload: dict, snapshot_dir: Path | None = None) -> Path:
    """Persist the payload locally (second copy). Timestamped to avoid clobbering
    an email-only backfill and a same-day plan push."""
    snapshot_dir = snapshot_dir or SNAPSHOT_DIR
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    kind = "plan" if payload.get("plan") else "emails"
    path = snapshot_dir / f"{payload['date']}-{kind}-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def push_snapshot(
    host: str,
    token: str | None,
    date: str,
    plan: str | None,
    emails: list[EmailItem],
    bundle: ContextBundle | None = None,
    *,
    snapshot_dir: Path | None = None,
    timeout: int = _TIMEOUT,
) -> bool:
    """Save a local snapshot, then best-effort POST to the phone's /ingest.

    Returns True if the phone acknowledged the push. Never raises — logs and
    returns False on any failure so the daily run always completes.
    """
    payload = build_payload(date, plan, emails, bundle)
    try:
        snap = save_snapshot(payload, snapshot_dir)
        log.info("Saved responder snapshot: %s", snap)
    except OSError as exc:
        log.warning("Could not write responder snapshot: %s", exc)

    if not host:
        log.info("No responder.ingest_host configured; skipping push.")
        return False

    url = f"http://{host}/ingest"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        log.info(
            "Pushed to responder %s: %d emails, plan=%s",
            host, len(emails), bool(plan),
        )
        return True
    except requests.RequestException as exc:
        log.warning("Responder push to %s failed (non-fatal): %s", url, exc)
        return False
