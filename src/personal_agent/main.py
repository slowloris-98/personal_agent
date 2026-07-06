"""Orchestrate the daily run: collect -> plan -> write.

Usage:
    python -m personal_agent.main             # collect, plan, and write to the Doc
    python -m personal_agent.main --dry-run   # collect + plan, print to stdout, no Doc write
    python -m personal_agent.main ask "..."   # ask a question of the memory layer
    python -m personal_agent.main seed --days 7   # backfill past days into memory
    python -m personal_agent.main memory graph    # export the knowledge graph to HTML
    python -m personal_agent.main memory ui       # open the local Cognee UI
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .collectors import calendar_collector, gmail_collector, tasks_collector
from .config import LOGS_DIR, MEMORY_DIR, load_config
from .docs_writer import prepend_plan
from .llm import get_provider
from .memory import get_memory_store
from .memory.base import NullMemoryStore
from .models import ContextBundle
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


def build_bundle_for_date(
    config,
    day: date,
    *,
    email_query: str | None = None,
    max_emails: int | None = None,
    include_tasks: bool = True,
) -> ContextBundle:
    """Assemble a ContextBundle for a specific day.

    `email_query` None -> the daily query (`email_query` + `email_filter`). The
    `seed` backfill passes an explicit dated `after:/before:` query. Tasks are
    optional because Google Tasks only exposes *current* state — including today's
    list in every historical day would be misleading, so backfill omits them.
    """
    warnings: list[str] = []
    primary = config.primary_account.label

    emails = gmail_collector.collect(
        config.accounts, config.collect, warnings,
        query=email_query, max_results=max_emails,
    )
    events = calendar_collector.collect(primary, config.collect, warnings, on_date=day)
    tasks = tasks_collector.collect(primary, warnings) if include_tasks else []

    return ContextBundle(
        date=day.strftime("%Y-%m-%d"),
        timezone=config.collect.timezone,
        emails=emails,
        events=events,
        tasks=tasks,
        warnings=warnings,
    )


def build_bundle(config) -> ContextBundle:
    """Today's bundle for the daily run (uses the default daily email query)."""
    today = datetime.now(ZoneInfo(config.collect.timezone)).date()
    return build_bundle_for_date(config, today, include_tasks=True)


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

    memory_store = get_memory_store(config)
    bundle.memory = memory_store.retrieve_for_bundle(bundle)
    if bundle.memory:
        log.info("Retrieved %d chars of past context from memory.", len(bundle.memory))

    provider = get_provider(
        config.llm.provider,
        config.llm.model,
        max_tokens=config.llm.max_tokens,
        api_key=config.api_key_for_provider(),
    )
    plan = generate_plan(bundle, provider)

    if dry_run:
        print("\n" + "=" * 60)
        print(f"DAILY PLAN (dry run) — {bundle.date}")
        print("=" * 60 + "\n")
        print(plan)
        return 0

    prepend_plan(config.primary_account.label, config.output.doc_id, bundle.date, plan)
    log.info("Done. Plan written to Google Doc.")

    # Persist this day into memory (real runs only, so dry-runs don't pollute it).
    memory_store.write(bundle, plan)
    return 0


def ask(question: str) -> int:
    """Answer an ad-hoc question from the memory layer and print it.

    The query logic lives in the memory store, so a future comms layer
    (text/WhatsApp) can reuse `MemoryStore.recall` directly.
    """
    config = load_config()
    memory_store = get_memory_store(config)
    log.info("Answering memory question: %s", question)
    answer = memory_store.recall(question)
    print(answer)
    return 0


def _dated_email_query(day: date, email_filter: str) -> str:
    """Gmail query scoping to a single day, plus the relevance filter."""
    nxt = day + timedelta(days=1)
    base = f"after:{day:%Y/%m/%d} before:{nxt:%Y/%m/%d}"
    return " ".join(p for p in (base, email_filter.strip()) if p)


def seed(days: int = 7, emails_per_account: int | None = None) -> int:
    """Backfill the last `days` days into memory, one entry per day.

    Runs oldest -> newest so a later day's plan is informed by earlier seeded
    days (mimicking real accumulation). Never writes to the Google Doc.
    """
    config = load_config()
    memory_store = get_memory_store(config)
    if isinstance(memory_store, NullMemoryStore):
        print(
            "Memory is disabled. Set memory.enabled: true in config.yaml and "
            "OPENAI_API_KEY in .env, then retry."
        )
        return 1

    provider = get_provider(
        config.llm.provider,
        config.llm.model,
        max_tokens=config.llm.max_tokens,
        api_key=config.api_key_for_provider(),
    )
    tz = ZoneInfo(config.collect.timezone)
    today = datetime.now(tz).date()

    log.info("Seeding %d day(s) into memory dataset '%s'.", days, config.memory.dataset_name)
    for offset in range(days, 0, -1):  # oldest first
        day = today - timedelta(days=offset)
        query = _dated_email_query(day, config.collect.email_filter)
        bundle = build_bundle_for_date(
            config, day,
            email_query=query, max_emails=emails_per_account, include_tasks=False,
        )
        bundle.memory = memory_store.retrieve_for_bundle(bundle)
        plan = generate_plan(bundle, provider)
        memory_store.write(bundle, plan)
        print(f"  seeded {day} — {len(bundle.emails)} emails, {len(bundle.events)} events")

    print(f"Done. Seeded {days} day(s) into memory dataset '{config.memory.dataset_name}'.")
    return 0


def memory_graph(out: str) -> int:
    """Export the memory knowledge graph to an HTML file."""
    memory_store = get_memory_store(load_config())
    path = memory_store.visualize(out)
    if path:
        print(f"Graph exported to {path}")
        return 0
    return 1


def memory_ui() -> int:
    """Launch the local Cognee UI to browse the memory graph."""
    get_memory_store(load_config()).serve_ui()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Personal daily-planning agent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect and plan, print to stdout, do not write to the Doc.",
    )
    sub = parser.add_subparsers(dest="command")

    ask_p = sub.add_parser("ask", help="Ask a question of the memory layer.")
    ask_p.add_argument("question", help="The question to ask memory.")

    seed_p = sub.add_parser("seed", help="Backfill past days into memory (one entry per day).")
    seed_p.add_argument("--days", type=int, default=7, help="How many past days to seed (default 7).")
    seed_p.add_argument(
        "--emails-per-account", type=int, default=None,
        help="Override the per-account per-day email cap (default: config value).",
    )

    mem_p = sub.add_parser("memory", help="Inspect the memory knowledge graph.")
    mem_sub = mem_p.add_subparsers(dest="memory_command")
    graph_p = mem_sub.add_parser("graph", help="Export the graph to an HTML file.")
    graph_p.add_argument("--out", default=str(MEMORY_DIR / "graph.html"), help="Output HTML path.")
    mem_sub.add_parser("ui", help="Launch the local Cognee UI.")

    args = parser.parse_args()
    _setup_logging()
    try:
        if args.command == "ask":
            return ask(args.question)
        if args.command == "seed":
            return seed(days=args.days, emails_per_account=args.emails_per_account)
        if args.command == "memory":
            if args.memory_command == "graph":
                return memory_graph(args.out)
            if args.memory_command == "ui":
                return memory_ui()
            mem_p.print_help()
            return 1
        return run(dry_run=args.dry_run)
    except Exception:
        log.exception("Run failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
