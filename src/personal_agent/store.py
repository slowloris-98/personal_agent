"""SQLite store for the responder — the phone-side source of truth.

This is the schema contract both machines agree on: the Windows PC pushes emails
and daily plans in via `sync_client`/`ingest_server`, and the Telegram responder
reads them back out to answer questions. It lives only on the always-on device;
the PC keeps JSON snapshots as a second copy (see `sync_client`).

Durability: the DB is opened in WAL mode with transactional writes, so an Android
process-kill mid-write rolls back cleanly rather than corrupting the file. The DB
is also fully reconstructable — emails re-fetch from Gmail (`scripts/backfill_emails`)
and plans also live in Notion/Docs — so the store is a rebuildable serving copy.

Tables:
  emails(gmail_id PK, account, sender, subject, snippet, received_at,
         received_ts, ingested_at)
  plans(date PK, plan_markdown, bundle_json, created_at)
  conversations(id PK, chat_id, role, content, ts)   -- per-chat history
  emails_fts                                          -- FTS5 over subject/snippet/sender

Functions take an open `sqlite3.Connection` (from `connect`/`init_db`) so tests can
run against an in-memory DB and the server can hold one long-lived connection.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from .models import EmailItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    gmail_id    TEXT PRIMARY KEY,
    account     TEXT NOT NULL,
    sender      TEXT NOT NULL,
    subject     TEXT NOT NULL,
    snippet     TEXT NOT NULL,
    received_at TEXT NOT NULL,
    received_ts REAL,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    date          TEXT PRIMARY KEY,
    plan_markdown TEXT NOT NULL,
    bundle_json   TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    role    TEXT NOT NULL,
    content TEXT NOT NULL,
    ts      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_chat ON conversations(chat_id, id);

-- Standalone FTS5 index (kept in sync manually in upsert_emails). gmail_id is
-- UNINDEXED so we can map matches back to the emails table.
CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
    gmail_id UNINDEXED, subject, snippet, sender
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a WAL-mode connection with a dict-like row factory."""
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(path: str | Path) -> sqlite3.Connection:
    """Open `path` (creating parent dirs) and ensure the schema exists."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _parse_received_ts(received_at: str) -> float | None:
    """Best-effort epoch seconds from an RFC 2822 Date header; None if unparseable."""
    if not received_at:
        return None
    try:
        dt = parsedate_to_datetime(received_at)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def upsert_emails(conn: sqlite3.Connection, emails: list[EmailItem]) -> int:
    """Insert-or-replace emails by gmail_id and keep the FTS index in sync.

    Emails without a gmail_id are skipped (no stable dedup key). Returns the count
    written. Runs in a single transaction so a crash leaves the DB consistent.
    """
    written = 0
    ingested_at = _now_iso()
    with conn:  # transaction: commit on success, rollback on exception
        for e in emails:
            if not e.gmail_id:
                continue
            received_ts = _parse_received_ts(e.received_at)
            conn.execute(
                "INSERT OR REPLACE INTO emails "
                "(gmail_id, account, sender, subject, snippet, received_at, "
                " received_ts, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (e.gmail_id, e.account, e.sender, e.subject, e.snippet,
                 e.received_at, received_ts, ingested_at),
            )
            conn.execute("DELETE FROM emails_fts WHERE gmail_id = ?", (e.gmail_id,))
            conn.execute(
                "INSERT INTO emails_fts (gmail_id, subject, snippet, sender) "
                "VALUES (?, ?, ?, ?)",
                (e.gmail_id, e.subject, e.snippet, e.sender),
            )
            written += 1
    return written


def upsert_plan(
    conn: sqlite3.Connection, date: str, plan_markdown: str, bundle_json: str | None = None
) -> None:
    """Insert-or-replace the plan for a given date (re-runs update in place)."""
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO plans (date, plan_markdown, bundle_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (date, plan_markdown, bundle_json, _now_iso()),
        )


def latest_plan(conn: sqlite3.Connection) -> dict | None:
    """The most recent plan by date, or None if the store is empty."""
    row = conn.execute(
        "SELECT date, plan_markdown, bundle_json, created_at FROM plans "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def plan_for_date(conn: sqlite3.Connection, date: str) -> dict | None:
    row = conn.execute(
        "SELECT date, plan_markdown, bundle_json, created_at FROM plans WHERE date = ?",
        (date,),
    ).fetchone()
    return dict(row) if row else None


def _fts_query(text: str) -> str | None:
    """Turn free text into a safe FTS5 MATCH expression (OR of quoted tokens)."""
    tokens = [t for t in "".join(c if c.isalnum() else " " for c in text).split() if t]
    if not tokens:
        return None
    return " OR ".join(f'"{t}"' for t in tokens)


def search_emails(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[dict]:
    """Keyword-search emails via FTS, newest matches first.

    Falls back to the most recent emails when `query` has no usable search terms.
    """
    match = _fts_query(query)
    if match is None:
        return recent_emails(conn, limit)
    rows = conn.execute(
        "SELECT e.gmail_id, e.account, e.sender, e.subject, e.snippet, "
        "       e.received_at, e.received_ts "
        "FROM emails_fts f JOIN emails e ON e.gmail_id = f.gmail_id "
        "WHERE emails_fts MATCH ? "
        "ORDER BY e.received_ts IS NULL, e.received_ts DESC LIMIT ?",
        (match, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def recent_emails(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT gmail_id, account, sender, subject, snippet, received_at, received_ts "
        "FROM emails ORDER BY received_ts IS NULL, received_ts DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def prune_emails(conn: sqlite3.Connection, older_than_days: int) -> int:
    """Delete emails older than the retention window; returns rows removed.

    Emails with an unparseable date (received_ts IS NULL) are kept — we never
    delete something we can't confidently age out.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - older_than_days * 86400
    with conn:
        stale = [
            r["gmail_id"]
            for r in conn.execute(
                "SELECT gmail_id FROM emails WHERE received_ts IS NOT NULL "
                "AND received_ts < ?",
                (cutoff,),
            ).fetchall()
        ]
        for gid in stale:
            conn.execute("DELETE FROM emails WHERE gmail_id = ?", (gid,))
            conn.execute("DELETE FROM emails_fts WHERE gmail_id = ?", (gid,))
    return len(stale)


def append_turn(conn: sqlite3.Connection, chat_id: str, role: str, content: str) -> None:
    """Record one conversation turn (role: 'user' or 'assistant')."""
    with conn:
        conn.execute(
            "INSERT INTO conversations (chat_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (str(chat_id), role, content, _now_iso()),
        )


def recent_turns(conn: sqlite3.Connection, chat_id: str, n: int = 10) -> list[dict]:
    """The last `n` turns for a chat, oldest-first (ready to feed back as history)."""
    rows = conn.execute(
        "SELECT role, content, ts FROM conversations WHERE chat_id = ? "
        "ORDER BY id DESC LIMIT ?",
        (str(chat_id), n),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def backup_to(conn: sqlite3.Connection, dest_path: str | Path) -> None:
    """Write a consistent copy of the DB to `dest_path` via SQLite's backup API."""
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(dest)) as target:
        conn.backup(target)
