"""The 24/7 communication layer that runs on the always-on device (phone/Termux).

Two long-running processes read/write the phone-local SQLite store (`..store`):

- `ingest_server`  — FastAPI endpoint the PC pushes the day's plan + emails to
                     (over Tailscale, bearer-token auth).
- `telegram_bot`   — long-polls Telegram, retrieves context from the store, and
                     answers your read-only questions via a switchable LLM.

Nothing here is imported by the daily PC pipeline; the phone deps live in the
`responder` optional extra (`pip install -e .[responder]`).
"""
