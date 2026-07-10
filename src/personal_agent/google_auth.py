"""Google OAuth: authorize accounts and build authorized API service clients.

One OAuth *client* (Desktop app) is shared across all accounts; each account is
authorized once and its token cached at credentials/token_<label>.json.
"""
from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import CREDENTIALS_DIR

# Least-privilege scopes. All accounts request the same set so a single token
# works for whichever service that account is used for.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
    "https://www.googleapis.com/auth/documents",
    # drive.file: create the weekly Doc inside the output folder and find it
    # again later. Only exposes files this app creates.
    "https://www.googleapis.com/auth/drive.file",
]

CLIENT_SECRET_PATH = CREDENTIALS_DIR / "client_secret.json"


def _token_path(label: str) -> Path:
    return CREDENTIALS_DIR / f"token_{label}.json"


def authorize_account(label: str) -> Credentials:
    """Run the interactive OAuth flow for one account and cache its token.

    Requires credentials/client_secret.json (the OAuth Desktop client). Opens a
    browser; sign in with the Gmail account you want to associate with `label`.
    """
    if not CLIENT_SECRET_PATH.exists():
        raise FileNotFoundError(
            f"Missing OAuth client secret at {CLIENT_SECRET_PATH}. "
            "Download it from Google Cloud Console (APIs & Services > Credentials > "
            "OAuth client ID, type 'Desktop app') and save it there."
        )
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    _token_path(label).write_text(creds.to_json(), encoding="utf-8")
    return creds


def load_credentials(label: str) -> Credentials:
    """Load a cached token for `label`, refreshing it if expired."""
    token_path = _token_path(label)
    if not token_path.exists():
        raise FileNotFoundError(
            f"No token for account '{label}'. Run: "
            f"python scripts/authorize.py {label}"
        )
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                f"Credentials for '{label}' are invalid and cannot be refreshed. "
                f"Re-run: python scripts/authorize.py {label}"
            )
    return creds


def get_service(label: str, api: str, version: str):
    """Return an authorized Google API client for `label`.

    e.g. get_service("acct1", "gmail", "v1"), ("primary_label", "calendar", "v3"),
         ("primary_label", "tasks", "v1"), ("primary_label", "docs", "v1").
    """
    creds = load_credentials(label)
    return build(api, version, credentials=creds, cache_discovery=False)
