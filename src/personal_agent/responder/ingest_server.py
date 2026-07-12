"""FastAPI ingest endpoint — the phone's inbox for pushes from the PC.

The PC's `sync_client.push_snapshot` POSTs the daily plan + emails here; we write
them into the phone-local store and prune anything past the retention window. This
is the only *write* surface on the device.

Security: bound to the Tailscale interface only (see run command below) and
protected by a bearer token shared with the PC (`INGEST_TOKEN`). No public
exposure, no port forwarding.

Run on the device:
    uvicorn personal_agent.responder.ingest_server:build_app --factory \
        --host <tailscale-ip> --port 8000
"""
from __future__ import annotations

import json
import logging
import secrets

from fastapi import Body, FastAPI, Header, HTTPException

from .. import store
from ..config import load_config
from ..models import EmailItem

log = logging.getLogger(__name__)

_EMAIL_FIELDS = {"account", "sender", "subject", "snippet", "received_at", "gmail_id"}


def _check_auth(authorization: str | None, token: str | None) -> None:
    if not token:
        raise HTTPException(status_code=503, detail="Ingest token not configured on device.")
    expected = f"Bearer {token}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Bad or missing bearer token.")


def _email_from_payload(raw: dict) -> EmailItem:
    """Build an EmailItem from a payload dict, ignoring unexpected keys."""
    return EmailItem(**{k: raw.get(k, "") for k in _EMAIL_FIELDS})


def create_app(conn, ingest_token: str | None, retention_days: int = 60) -> FastAPI:
    """Build the app around an open store connection (injectable for tests)."""
    app = FastAPI(title="personal-agent responder ingest")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/ingest")
    def ingest(
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ) -> dict:
        _check_auth(authorization, ingest_token)

        emails = [_email_from_payload(e) for e in payload.get("emails", [])]
        n_emails = store.upsert_emails(conn, emails)

        plan = payload.get("plan")
        wrote_plan = False
        if plan:
            date = payload.get("date")
            if not date:
                raise HTTPException(status_code=422, detail="Plan push missing 'date'.")
            bundle = payload.get("bundle")
            store.upsert_plan(
                conn, date, plan, json.dumps(bundle) if bundle is not None else None
            )
            wrote_plan = True

        pruned = store.prune_emails(conn, retention_days)
        log.info(
            "Ingest: %d emails, plan=%s, pruned=%d", n_emails, wrote_plan, pruned
        )
        return {"emails_written": n_emails, "plan_written": wrote_plan, "pruned": pruned}

    return app


def build_app() -> FastAPI:
    """Factory for uvicorn: load config, open the store, wire the app."""
    config = load_config()
    conn = store.init_db(config.responder.db_path)
    return create_app(conn, config.ingest_token, config.responder.retention_days)
