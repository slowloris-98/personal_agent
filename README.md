# Personal Daily-Planning Agent

Each morning this agent reads your email across **3 Gmail accounts**, pulls **today's Google
Calendar** events and your **open Google Tasks**, asks an LLM to build a focused day plan, and
writes it out to your chosen target: by default **one formatted Google Doc per day** in a Drive
folder, or a **Notion page tree**.

- Runs unattended via **Windows Task Scheduler**.
- **Swappable LLM**: `claude_code` (default, no API key), `anthropic`, `openai`, or `groq`.
- **Swappable output**: Google Docs (default) or Notion.
- Read-only Google access (Gmail / Calendar / Tasks) + `drive.file` write access limited to the
  plan folder and Docs the agent itself creates.

## Architecture

```
Gmail x3 ─┐                                                    ┌─► per-day Google Doc (Drive Markdown import)
Calendar ─┼─► collectors ─► ContextBundle ─► LLM provider ─► plan ─┤
Tasks ────┘                                  (swappable)          └─► Notion page tree
```

Layout: [src/personal_agent/](src/personal_agent/) holds the package (`config`, `google_auth`,
`collectors/`, `llm/`, `planner`, `docs_writer`, `notion_writer`, `main`); [scripts/](scripts/)
holds `authorize.py` and `run_daily.ps1`; [tests/](tests/) holds unit tests.

## Setup

### 1. Install

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -e .
```

This installs the package (from [pyproject.toml](pyproject.toml)) along with its dependencies, so
`python -m personal_agent.main` resolves from any directory. `requirements.txt` is still provided if
you prefer `pip install -r requirements.txt`, but then you must run with `PYTHONPATH=src`.

### 2. Google Cloud project (one-time)

1. Create a project at <https://console.cloud.google.com/>.
2. **APIs & Services → Enable APIs**: enable **Gmail API**, **Google Calendar API**,
   **Google Tasks API**, **Google Docs API**, and **Google Drive API** (the daily Doc is
   created through Drive's Markdown importer).
3. **OAuth consent screen**: User type **External**, publishing status **Testing**. Under
   **Test users**, add all three of your Gmail addresses (Testing mode only lets listed users
   authorize).
4. **Credentials → Create credentials → OAuth client ID → Desktop app**. Download the JSON and
   save it as `credentials/client_secret.json`.

Scopes requested (least privilege): `gmail.readonly`, `calendar.events.readonly`,
`tasks.readonly`, `documents`, and `drive.file`. `drive.file` only exposes files this app
creates — it's what lets the agent make and own the plan folder and per-day Docs without
touching the rest of your Drive.

### 3. Authorize each account (one-time)

```powershell
python scripts/authorize.py acct1   # sign in with your PRIMARY account
python scripts/authorize.py acct2
python scripts/authorize.py acct3
```

Each opens a browser and writes `credentials/token_<label>.json`. The `acct*` labels must match
`config.yaml`. The **primary** account (whichever you mark `primary: true`) owns Calendar, Tasks,
and the output Doc.

### 4. Configure

Edit [config.yaml](config.yaml): account labels/names, `collect.timezone`,
`collect.email_query`, the LLM `provider`/`model`, and the `output` block.

Accounts take a stable `label` (the token-file key — don't rename once authorized) and an
optional display `name` (how the account is tagged in the plan, e.g. `Personal` / `Work` /
`College`; defaults to `label`).

Output target is set by `output.target`:

- **`google_docs`** (default) — no manual Doc to create. The agent auto-creates and owns a
  Drive folder named `output.folder_name` (default `"Daily Plans"`) and drops one Doc per day
  into it. Optionally set `output.folder_id` to a specific Drive folder id to write there
  instead — but under the narrow `drive.file` scope that folder must be one this app created,
  so leave it blank unless you know it qualifies.
- **`notion`** — see [Output to Notion](#output-to-notion-alternative-to-google-docs) below;
  set `output.notion_root_page_id`.

LLM keys:

- **`claude_code`** (default) needs no key — it shells out to your local `claude` CLI.
- For `anthropic` / `openai` / `groq`: copy `.env.example` to `.env` and set the matching key.

### Output to Notion (alternative to Google Docs)

Instead of per-day Google Docs, plans can go into Notion as a page tree:
**Daily Planning → one subpage per ISO week → one subpage per day** (the day's
Markdown is dumped straight in via Notion's Markdown Content API). One-time setup:

1. Create an **internal integration** at <https://www.notion.com/my-integrations>,
   copy its token, and add it to `.env` as `NOTION_API_KEY`.
2. Create a page named **"Daily Planning"** in Notion, then **share it with the
   integration** (page ⋯ menu → *Connections* → your integration). Integrations
   only see pages explicitly shared with them.
3. Copy that page's id from its URL (the 32-char id after the title) into
   `config.yaml` → `output.notion_root_page_id`, and set `output.target: notion`.

This path is write-only: created page ids are cached in
`credentials/notion_state.json` so re-runs update the day's page instead of
duplicating it. Because Notion renders Markdown tables, the planner is allowed to
use tables when this target is selected.

## Run

```powershell
# Dry run: collect + plan, print to stdout, do NOT write any output
python -m personal_agent.main --dry-run

# Real run: also writes the plan to the configured target
#   google_docs -> creates (or replaces) today's Doc in the Drive folder
#   notion      -> creates (or replaces) today's page under the weekly subpage
python -m personal_agent.main
```

## Schedule it (Windows Task Scheduler)

Run daily at 06:30, calling the wrapper script:

```powershell
schtasks /Create /TN "PersonalDailyPlanner" /SC DAILY /ST 06:30 ^
  /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"d:\Atreya\College\Projects\personal_agent\scripts\run_daily.ps1\""
```

Then test it immediately:

```powershell
schtasks /Run /TN "PersonalDailyPlanner"
```

Logs are written to [logs/agent.log](logs/). The run continues on partial failure (e.g. one
account's fetch fails) and notes it in the plan under a warnings section.

## Testing

```powershell
python -m pytest tests/ -q
```

Covers provider selection (`test_factory`), prompt assembly (`test_planner`), the Google Docs
writer (`test_docs_writer`), and the Notion writer (`test_notion_writer`) with fakes — no
network or credentials needed.

## Swapping the LLM

Change `llm.provider` in `config.yaml` to `claude_code | anthropic | openai | groq` and set
`llm.model` accordingly (e.g. `claude-opus-4-8`, `gpt-4o`, `llama-3.3-70b-versatile`). Add the
provider's key to `.env` (none needed for `claude_code`). Add a new provider by implementing
`LLMProvider.generate` in [src/personal_agent/llm/](src/personal_agent/llm/) and registering it in
`factory.py`.
