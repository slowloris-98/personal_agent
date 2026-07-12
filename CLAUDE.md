# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A personal daily-planning agent. Each morning it reads email across 3 Gmail accounts, today's
Google Calendar events, and open Google Tasks; asks a swappable LLM to build a focused day plan
(GitHub-flavored Markdown); and writes it to a configurable output target. Designed to run
unattended via Windows Task Scheduler.

## Pipeline

```
collectors ─► ContextBundle ─► LLM provider ─► Markdown plan ─► output target
```

- **Collectors** — [src/personal_agent/collectors/](src/personal_agent/collectors/):
  `gmail_collector`, `calendar_collector`, `tasks_collector`. Gmail runs per account and
  continues on partial failure, noting the failure in a warnings section of the plan.
- **Bundle** — `ContextBundle` in [models.py](src/personal_agent/models.py) carries the
  collected emails/events/tasks plus the date.
- **Planner** — [planner.py](src/personal_agent/planner.py). `generate_plan(bundle, provider,
  allow_tables)` builds the system + user prompt and calls the provider. `allow_tables` gates
  whether the LLM may emit Markdown tables — driven by the output target.
- **LLM providers** — [src/personal_agent/llm/](src/personal_agent/llm/). Abstract
  `LLMProvider.generate` with a `factory.py`. `claude_code` (default) shells out to the local
  `claude` CLI and needs no key; `anthropic` / `openai` / `groq` read keys from `.env`. Add a
  provider by implementing `generate` and registering it in `factory.py`.

## Output targets

Dispatch lives in `_write_plan` in [main.py](src/personal_agent/main.py), keyed on
`config.output.target`:

- **`google_docs`** (default) — [docs_writer.py](src/personal_agent/docs_writer.py)
  `write_day_doc`. Uploads the plan Markdown to Drive with the native Markdown importer, which
  produces a fully formatted Doc. One Doc per day, named `<date> — Daily Plan`, inside a Drive
  folder the agent creates and owns (`output.folder_name`), or an explicit `output.folder_id`.
  A re-run for the same day replaces that day's Doc. Uses the `drive.file` scope only.
- **`notion`** — [notion_writer.py](src/personal_agent/notion_writer.py) `write_plan`. Builds a
  page tree under a shared "Daily Planning" page (`output.notion_root_page_id`): one weekly
  subpage, then one day subpage per day, via Notion's Markdown Content API. Write-only;
  created page ids are cached in `credentials/notion_state.json` so re-runs update rather than
  duplicate. Token from `NOTION_API_KEY` in `.env`.

## Communication layer (24/7 responder)

An optional two-machine chat layer lets you talk to the agent over **Telegram**, even when the
Windows PC is asleep. Off by default (`responder.enabled: false`); enabling it adds a second data
flow alongside the daily plan:

```
  Windows PC (nightly)                          Android phone / Termux (always-on)
  daily run ─► _push_snapshot ──HTTP/Tailscale──► ingest_server ─► SQLite store ◄─ telegram_bot ◄─► you
                                                                    (retrieval ─► switchable LLM)
```

- **Store** — [store.py](src/personal_agent/store.py): the phone-local SQLite source of truth
  (emails, plans, conversation history; FTS5 email search; WAL for crash-safety). Schema is the
  contract both machines share. Rebuildable from Gmail + Notion/Docs, so it's a serving copy.
- **PC push** — [sync_client.py](src/personal_agent/sync_client.py) `push_snapshot`, called by
  `_push_snapshot` in [main.py](src/personal_agent/main.py) after the plan is written. Best-effort
  (never fails the daily run); also writes a durable JSON copy to `data/snapshots/`. Seed history
  once with `scripts/backfill_emails.py` (default 60 days).
- **Responder** — [src/personal_agent/responder/](src/personal_agent/responder/) (phone-only deps,
  `pip install -e .[responder]`): `ingest_server.py` (FastAPI `/ingest`, bearer-token auth, bound
  to the Tailscale interface); `telegram_bot.py` (long-polling, allow-listed `chat_id`, `/model`
  switch); `retrieval.py` + `answer.py` (assemble context, read-only Q&A via an injected provider).
- **Switchable answer LLM** — reuses the `LLMProvider` factory; `responder.provider` picks
  `anthropic | openai | ollama` (local via [ollama_provider.py](src/personal_agent/llm/ollama_provider.py)).
  Independent of the heavier `llm.provider` used to generate the plan.
- **Config** — `responder` block in [config.yaml](config.yaml) (read by both machines); secrets
  `INGEST_TOKEN` (shared PC↔phone), `TELEGRAM_BOT_TOKEN`, optional `OLLAMA_HOST` in `.env`.

Deployment (phone, Android 13 → Termux): `pkg install python`, `pip install -e .[responder]`, copy
`config.yaml` + `.env`, install **Tailscale** on both machines, then run the two processes —
`uvicorn personal_agent.responder.ingest_server:build_app --factory --host <tailscale-ip> --port 8000`
and `python -m personal_agent.responder.telegram_bot`. Use **Termux:Boot** + `termux-wake-lock` to
auto-start and survive Doze, and disable battery optimization for Termux. Back up the DB periodically
(`store.backup_to`) to `/sdcard` and/or the PC. A Raspberry Pi / mini-PC is a drop-in host if the
phone proves flaky.

## Config & secrets

- Structure in [config.yaml](config.yaml); secrets (LLM + Notion keys) in `.env` (see
  `.env.example`). Loaded by [config.py](src/personal_agent/config.py) (`load_config`).
- Accounts: `label` is the stable token-file key (`credentials/token_<label>.json`); `name` is
  a display-only override (`Account.display_name` falls back to `label`).
- Google OAuth scopes are defined in [google_auth.py](src/personal_agent/google_auth.py)
  (`SCOPES`): `gmail.readonly`, `calendar.events.readonly`, `tasks.readonly`, `documents`,
  `drive.file`. `scripts/authorize.py` runs the one-time per-account OAuth flow.

## Dev commands

```powershell
pip install -e .                             # install package + deps (from pyproject.toml)
pip install -e ".[dev]"                      # + test/responder deps (fastapi, httpx)
python -m personal_agent.main --dry-run      # collect + plan, print, write nothing
python -m personal_agent.main                # real run: writes to the configured target
python -m pytest tests/ -q                   # unit tests (fakes; no network/credentials)

# Responder (only if responder.enabled) — see "Communication layer" above.
python scripts/backfill_emails.py            # one-time: seed 60 days of email to the phone
pip install -e ".[responder]"                # on the phone: fastapi + uvicorn
python -m personal_agent.responder.telegram_bot   # on the phone: start the chat bot
```

Tests cover the factory, planner, docs writer, notion writer, and the responder (store, sync
client, ingest server, retrieval/answer, telegram bot) with fakes.

## Environment

Windows 11, PowerShell. Paths and the Task Scheduler wrapper (`scripts/run_daily.ps1`) are
Windows-oriented. Logs go to `logs/agent.log`.
