import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from personal_agent import sync_client  # noqa: E402
from personal_agent.models import ContextBundle, EmailItem  # noqa: E402

EMAILS = [
    EmailItem("Personal", "a@b.com", "Invoice", "please pay", "Wed, 09 Jul 2026 10:00:00 +0000", "g1"),
    EmailItem("Work", "c@d.com", "Standup", "9am", "Wed, 09 Jul 2026 08:00:00 +0000", "g2"),
]
BUNDLE = ContextBundle(date="2026-07-11", timezone="UTC", emails=EMAILS)


class FakeResp:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"status {self.status_code}")


class FakeRequests:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp or FakeResp(), exc, []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "body": json, "timeout": timeout})
        if self.exc:
            raise self.exc
        return self.resp

    # sync_client references requests.RequestException / HTTPError on the module.
    RequestException = __import__("requests").RequestException


def test_build_payload_shape():
    payload = sync_client.build_payload("2026-07-11", "### Plan", EMAILS, BUNDLE)
    assert payload["date"] == "2026-07-11"
    assert payload["plan"] == "### Plan"
    assert [e["gmail_id"] for e in payload["emails"]] == ["g1", "g2"]
    assert payload["bundle"]["date"] == "2026-07-11"
    assert payload["emails"][0]["subject"] == "Invoice"


def test_build_payload_email_only():
    payload = sync_client.build_payload("2026-07-11", None, EMAILS, None)
    assert payload["plan"] is None
    assert payload["bundle"] is None


def test_push_saves_snapshot_and_posts(tmp_path, monkeypatch):
    fake = FakeRequests()
    monkeypatch.setattr(sync_client, "requests", fake)

    ok = sync_client.push_snapshot(
        "phone-ts:8000", "sekret", "2026-07-11", "### Plan", EMAILS, BUNDLE,
        snapshot_dir=tmp_path,
    )
    assert ok is True

    # Posted to the right URL with bearer auth and the full payload.
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["url"] == "http://phone-ts:8000/ingest"
    assert call["headers"]["Authorization"] == "Bearer sekret"
    assert call["body"]["date"] == "2026-07-11"

    # Local snapshot written as a durable second copy.
    snaps = list(tmp_path.glob("2026-07-11-plan-*.json"))
    assert len(snaps) == 1
    saved = json.loads(snaps[0].read_text(encoding="utf-8"))
    assert [e["gmail_id"] for e in saved["emails"]] == ["g1", "g2"]


def test_push_failure_is_nonfatal_but_snapshot_kept(tmp_path, monkeypatch):
    import requests
    fake = FakeRequests(exc=requests.ConnectionError("phone offline"))
    monkeypatch.setattr(sync_client, "requests", fake)

    ok = sync_client.push_snapshot(
        "phone-ts:8000", "sekret", "2026-07-11", None, EMAILS,
        snapshot_dir=tmp_path,
    )
    assert ok is False  # push failed, but did not raise
    # Snapshot still saved despite the push failure (email-only -> "-emails-").
    assert list(tmp_path.glob("2026-07-11-emails-*.json"))


def test_push_skips_when_no_host(tmp_path, monkeypatch):
    fake = FakeRequests()
    monkeypatch.setattr(sync_client, "requests", fake)

    ok = sync_client.push_snapshot(
        "", "sekret", "2026-07-11", "### Plan", EMAILS, snapshot_dir=tmp_path,
    )
    assert ok is False
    assert fake.calls == []                     # no network call attempted
    assert list(tmp_path.glob("*.json"))        # but snapshot still saved
