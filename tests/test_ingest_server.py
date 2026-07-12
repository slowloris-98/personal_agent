import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from personal_agent import store  # noqa: E402
from personal_agent.responder.ingest_server import create_app  # noqa: E402

TOKEN = "shared-secret"

PLAN_PAYLOAD = {
    "date": "2026-07-11",
    "plan": "### Top priorities\n- Ship it",
    "emails": [
        {"account": "Personal", "sender": "a@b.com", "subject": "Invoice",
         "snippet": "please pay", "received_at": "Wed, 09 Jul 2026 10:00:00 +0000",
         "gmail_id": "g1"},
    ],
    "bundle": {"date": "2026-07-11", "timezone": "UTC", "events": [], "tasks": []},
}


@pytest.fixture
def ctx():
    conn = store.init_db(":memory:")
    app = create_app(conn, TOKEN, retention_days=60)
    yield conn, TestClient(app)
    conn.close()


def _auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_health_open(ctx):
    _, client = ctx
    assert client.get("/health").json() == {"ok": True}


def test_ingest_writes_emails_and_plan(ctx):
    conn, client = ctx
    resp = client.post("/ingest", json=PLAN_PAYLOAD, headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"emails_written": 1, "plan_written": True, "pruned": 0}

    # Landed in the store and is readable back.
    assert store.latest_plan(conn)["plan_markdown"].startswith("### Top priorities")
    assert store.plan_for_date(conn, "2026-07-11")["bundle_json"] is not None
    assert [e["gmail_id"] for e in store.recent_emails(conn)] == ["g1"]


def test_ingest_rejects_missing_token(ctx):
    _, client = ctx
    assert client.post("/ingest", json=PLAN_PAYLOAD).status_code == 401


def test_ingest_rejects_wrong_token(ctx):
    _, client = ctx
    resp = client.post("/ingest", json=PLAN_PAYLOAD, headers=_auth("nope"))
    assert resp.status_code == 401


def test_email_only_push_skips_plan(ctx):
    conn, client = ctx
    payload = {"date": "2026-07-11", "plan": None, "bundle": None,
               "emails": PLAN_PAYLOAD["emails"]}
    resp = client.post("/ingest", json=payload, headers=_auth())
    assert resp.json()["plan_written"] is False
    assert store.latest_plan(conn) is None
    assert len(store.recent_emails(conn)) == 1


def test_ingest_is_idempotent_on_repush(ctx):
    conn, client = ctx
    client.post("/ingest", json=PLAN_PAYLOAD, headers=_auth())
    client.post("/ingest", json=PLAN_PAYLOAD, headers=_auth())
    assert len(store.recent_emails(conn)) == 1  # deduped by gmail_id


def test_missing_token_config_returns_503(ctx):
    conn, _ = ctx
    client = TestClient(create_app(conn, ingest_token=None))
    resp = client.post("/ingest", json=PLAN_PAYLOAD, headers=_auth())
    assert resp.status_code == 503
