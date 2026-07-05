"""One-time OAuth authorization for a Gmail account.

Usage:
    python scripts/authorize.py acct1
    python scripts/authorize.py acct2
    python scripts/authorize.py acct3

Opens a browser; sign in with the account you want to bind to that label.
The label must match a `label` in config.yaml. Writes credentials/token_<label>.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make src/ importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_agent.google_auth import authorize_account  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/authorize.py <account_label>")
        return 2
    label = sys.argv[1]
    creds = authorize_account(label)

    # Confirm which address we just authorized.
    from googleapiclient.discovery import build

    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = gmail.users().getProfile(userId="me").execute()
    print(f"Authorized '{label}' -> {profile.get('emailAddress')}")
    print(f"Token saved. You can now use label '{label}' in config.yaml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
