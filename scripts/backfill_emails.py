"""One-time seed: push the last N days of email into the responder store.

The daily run only pushes that day's emails, so the phone DB grows forward from
whenever you enable it. Run this once to backfill history (default 60 days) across
all configured accounts.

Usage:
    python scripts/backfill_emails.py                 # 60 days, all accounts
    python scripts/backfill_emails.py --days 90
    python scripts/backfill_emails.py --max 500 --days 60

Requires `responder.enabled` + `responder.ingest_host` in config.yaml and
INGEST_TOKEN in .env (same as the daily run). Reuses the Gmail collector, so the
accounts must already be authorized (scripts/authorize.py).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Make src/ importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_agent.collectors import gmail_collector  # noqa: E402
from personal_agent.config import load_config  # noqa: E402
from personal_agent.sync_client import push_snapshot  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill email history to the responder store.")
    parser.add_argument("--days", type=int, default=60, help="How many days back to fetch.")
    parser.add_argument("--max", type=int, default=500,
                        help="Max messages per account (Gmail list cap).")
    args = parser.parse_args()

    config = load_config()
    if not config.responder.enabled or not config.responder.ingest_host:
        print("responder.enabled + responder.ingest_host must be set in config.yaml.")
        return 2

    query = f"newer_than:{args.days}d"
    today = datetime.now(ZoneInfo(config.collect.timezone)).strftime("%Y-%m-%d")

    all_emails = []
    for acct in config.accounts:
        try:
            items = gmail_collector.collect_for_account(
                acct.label, query, args.max, display_name=acct.display_name
            )
            print(f"  {acct.display_name}: {len(items)} messages")
            all_emails.extend(items)
        except Exception as exc:  # noqa: BLE001 — report and continue per account
            print(f"  {acct.display_name}: FAILED — {exc}")

    print(f"Pushing {len(all_emails)} emails (last {args.days}d) to {config.responder.ingest_host} ...")
    ok = push_snapshot(
        config.responder.ingest_host,
        config.ingest_token,
        today,
        None,               # email-only backfill: no plan
        all_emails,
        None,
    )
    print("Done." if ok else "Push failed (see warnings). A local snapshot was still saved.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
