import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from personal_agent import store  # noqa: E402
from personal_agent.models import EmailItem  # noqa: E402


def _email(gmail_id, subject="Hello", snippet="body", sender="a@b.com",
           account="Personal", received_at=None, days_ago=0):
    if received_at is None:
        dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        received_at = format_datetime(dt)
    return EmailItem(
        account=account, sender=sender, subject=subject, snippet=snippet,
        received_at=received_at, gmail_id=gmail_id,
    )


@pytest.fixture
def conn():
    c = store.init_db(":memory:")
    yield c
    c.close()


def test_upsert_and_recent_emails(conn):
    written = store.upsert_emails(conn, [_email("1"), _email("2")])
    assert written == 2
    rows = store.recent_emails(conn)
    assert {r["gmail_id"] for r in rows} == {"1", "2"}


def test_upsert_dedups_by_gmail_id(conn):
    store.upsert_emails(conn, [_email("1", subject="Old")])
    store.upsert_emails(conn, [_email("1", subject="New")])
    rows = store.recent_emails(conn)
    assert len(rows) == 1
    assert rows[0]["subject"] == "New"


def test_email_without_gmail_id_is_skipped(conn):
    written = store.upsert_emails(conn, [_email("")])
    assert written == 0
    assert store.recent_emails(conn) == []


def test_fts_search_matches_subject_and_stays_in_sync(conn):
    store.upsert_emails(conn, [
        _email("1", subject="Invoice for March", snippet="please pay"),
        _email("2", subject="Team lunch", snippet="pizza friday"),
    ])
    hits = store.search_emails(conn, "invoice")
    assert [h["gmail_id"] for h in hits] == ["1"]

    # Re-upserting the same id must not leave a stale FTS row behind.
    store.upsert_emails(conn, [_email("1", subject="Team lunch too", snippet="pizza")])
    assert store.search_emails(conn, "invoice") == []
    assert {h["gmail_id"] for h in store.search_emails(conn, "pizza")} == {"1", "2"}


def test_search_empty_query_falls_back_to_recent(conn):
    store.upsert_emails(conn, [_email("1"), _email("2")])
    hits = store.search_emails(conn, "!!!", limit=1)
    assert len(hits) == 1


def test_prune_removes_old_but_keeps_undated(conn):
    store.upsert_emails(conn, [
        _email("old", days_ago=90),
        _email("fresh", days_ago=1),
        _email("undated", received_at="not a real date"),
    ])
    removed = store.prune_emails(conn, older_than_days=60)
    assert removed == 1
    remaining = {r["gmail_id"] for r in store.recent_emails(conn)}
    assert remaining == {"fresh", "undated"}
    # FTS index pruned in lockstep — the old row is no longer searchable.
    assert store.search_emails(conn, "hello", limit=50)  # fresh/undated still match
    assert all(h["gmail_id"] != "old" for h in store.search_emails(conn, "hello", limit=50))


def test_plans_upsert_latest_and_by_date(conn):
    store.upsert_plan(conn, "2026-07-10", "### Mon", '{"a":1}')
    store.upsert_plan(conn, "2026-07-11", "### Tue")
    assert store.latest_plan(conn)["date"] == "2026-07-11"
    assert store.plan_for_date(conn, "2026-07-10")["plan_markdown"] == "### Mon"
    assert store.plan_for_date(conn, "2026-07-10")["bundle_json"] == '{"a":1}'

    # Re-run same day replaces content in place, no duplicate row.
    store.upsert_plan(conn, "2026-07-11", "### Tue v2")
    assert store.plan_for_date(conn, "2026-07-11")["plan_markdown"] == "### Tue v2"


def test_latest_plan_empty(conn):
    assert store.latest_plan(conn) is None


def test_conversation_history_roundtrip(conn):
    for i in range(5):
        store.append_turn(conn, "chat1", "user", f"q{i}")
        store.append_turn(conn, "chat1", "assistant", f"a{i}")
    store.append_turn(conn, "other", "user", "different chat")

    # Last 4 turns for chat1, oldest-first, scoped to that chat only.
    turns = store.recent_turns(conn, "chat1", n=4)
    assert [t["content"] for t in turns] == ["q3", "a3", "q4", "a4"]
    assert [t["role"] for t in turns] == ["user", "assistant", "user", "assistant"]


def test_backup_creates_restorable_copy(conn, tmp_path):
    store.upsert_emails(conn, [_email("1", subject="Keep me")])
    dest = tmp_path / "backup" / "agent.db"
    store.backup_to(conn, dest)

    restored = store.connect(dest)
    rows = store.recent_emails(restored)
    assert [r["subject"] for r in rows] == ["Keep me"]
    restored.close()
