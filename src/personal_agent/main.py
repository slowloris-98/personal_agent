"""Orchestrate the daily run: collect -> plan -> write.

Usage:
    python -m personal_agent.main            # collect, plan, and write to the Doc
    python -m personal_agent.main --dry-run  # collect + plan, print to stdout, no Doc write
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .collectors import calendar_collector, gmail_collector, tasks_collector
from .config import LOGS_DIR, load_config
from .docs_writer import write_day_doc
from .llm import get_provider
from .models import ContextBundle
from .notion_writer import write_plan
from .planner import generate_plan

log = logging.getLogger("personal_agent")


def _setup_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOGS_DIR / "agent.log", encoding="utf-8"),
        ],
    )


def build_bundle(config) -> ContextBundle:
    warnings: list[str] = []
    primary = config.primary_account.label
    today = datetime.now(ZoneInfo(config.collect.timezone)).strftime("%Y-%m-%d")

    emails = gmail_collector.collect(config.accounts, config.collect, warnings)
    events = calendar_collector.collect(primary, config.collect, warnings)
    tasks = tasks_collector.collect(primary, warnings)

    return ContextBundle(
        date=today,
        timezone=config.collect.timezone,
        emails=emails,
        events=events,
        tasks=tasks,
        warnings=warnings,
    )


def run(dry_run: bool = False) -> int:
    config = load_config()
    log.info(
        "Starting daily run — provider=%s, accounts=%d, dry_run=%s",
        config.llm.provider,
        len(config.accounts),
        dry_run,
    )

    bundle = build_bundle(config)
    log.info(
        "Collected: %d emails, %d events, %d tasks (%d warnings)",
        len(bundle.emails),
        len(bundle.events),
        len(bundle.tasks),
        len(bundle.warnings),
    )

    provider = get_provider(
        config.llm.provider,
        config.llm.model,
        max_tokens=config.llm.max_tokens,
        api_key=config.api_key_for_provider(),
    )
    # Both targets render Markdown tables natively (Notion's API and Google Drive's
    # Markdown importer), so tables are fine either way.
    allow_tables = config.output.target in {"notion", "google_docs"}
    plan = generate_plan(bundle, provider, allow_tables=allow_tables)

    if dry_run:
        print("\n" + "=" * 60)
        print(f"DAILY PLAN (dry run) — {bundle.date}")
        print("=" * 60 + "\n")
        print(plan)
        return 0

    _write_plan(config, bundle.date, plan)
    _push_snapshot(config, bundle, plan)
    return 0


def _write_plan(config, date: str, plan: str) -> None:
    """Dispatch the finished plan to the configured output target."""
    target = config.output.target
    if target == "google_docs":
        write_day_doc(
            config.primary_account.label,
            config.output.folder_id,
            config.output.folder_name,
            date,
            plan,
        )
        log.info("Done. Plan written to Google Doc.")
    elif target == "notion":
        write_plan(config.notion_token, config.output.notion_root_page_id, date, plan)
        log.info("Done. Plan written to Notion.")
    else:
        raise ValueError(
            f"Unknown output.target '{target}'. Choose one of: google_docs, notion."
        )


def _push_snapshot(config, bundle: ContextBundle, plan: str) -> None:
    """Push the day's plan + emails to the 24/7 responder, if enabled.

    Best-effort: never fails the daily run (the plan is already written above).
    """
    if not config.responder.enabled:
        return
    from .sync_client import push_snapshot

    push_snapshot(
        config.responder.ingest_host,
        config.ingest_token,
        bundle.date,
        plan,
        bundle.emails,
        bundle,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Personal daily-planning agent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect and plan, print to stdout, do not write to the Doc.",
    )
    args = parser.parse_args()
    _setup_logging()
    try:
        return run(dry_run=args.dry_run)
    except Exception:
        log.exception("Daily run failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
