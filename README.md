# Personal Daily-Planning Agent

Each morning this agent reads your email across **3 Gmail accounts**, pulls **today's Google
Calendar** events and your **open Google Tasks**, asks an LLM to build a focused day plan, and
**prepends that plan to the top of one rolling Google Doc**.

- Runs unattended via **Windows Task Scheduler**.
- **Swappable LLM**: `claude_code` (default, no API key), `anthropic`, `openai`, or `groq`.
- Read-only Google access (Gmail / Calendar / Tasks) + write access to the single output Doc.

## Architecture

```
Gmail x3 ─┐
Calendar ─┼─► collectors ─► ContextBundle ─► LLM provider ─► Markdown plan ─► rolling Google Doc
Tasks ────┘                                  (swappable)
```

Layout: [src/personal_agent/](src/personal_agent/) holds the package (`config`, `google_auth`,
`collectors/`, `llm/`, `planner`, `docs_writer`, `main`); [scripts/](scripts/) holds `authorize.py`
and `run_daily.ps1`; [tests/](tests/) holds unit tests.

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
   **Google Tasks API**, and **Google Docs API**.
3. **OAuth consent screen**: User type **External**, publishing status **Testing**. Under
   **Test users**, add all three of your Gmail addresses (Testing mode only lets listed users
   authorize).
4. **Credentials → Create credentials → OAuth client ID → Desktop app**. Download the JSON and
   save it as `credentials/client_secret.json`.

Scopes requested (least privilege): `gmail.readonly`, `calendar.events.readonly`,
`tasks.readonly`, and `documents` (to edit the one output doc).

### 3. Authorize each account (one-time)

```powershell
python scripts/authorize.py acct1   # sign in with your PRIMARY account
python scripts/authorize.py acct2
python scripts/authorize.py acct3
```

Each opens a browser and writes `credentials/token_<label>.json`. The `acct*` labels must match
`config.yaml`. The **primary** account (whichever you mark `primary: true`) owns Calendar, Tasks,
and the output Doc.

### 4. Create the rolling Doc

Create a blank Google Doc **with your primary account**, open it, and copy the ID from the URL:

```
https://docs.google.com/document/d/<THIS_IS_THE_DOC_ID>/edit
```

Paste it into `config.yaml` under `output.doc_id`.

### 5. Configure

Edit [config.yaml](config.yaml): account labels, `collect.timezone`, `collect.email_query`,
the LLM `provider`/`model`, and `output.doc_id`.

- **`claude_code`** (default) needs no key — it shells out to your local `claude` CLI.
- For `anthropic` / `openai` / `groq`: copy `.env.example` to `.env` and set the matching key.

## Run

```powershell
# Dry run: collect + plan, print to stdout, do NOT touch the Doc
python -m personal_agent.main --dry-run

# Real run: also prepends the plan to the top of the rolling Doc
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

Covers provider selection (`test_factory`) and prompt assembly (`test_planner`) with a fake
provider — no network or credentials needed.

## Swapping the LLM

Change `llm.provider` in `config.yaml` to `claude_code | anthropic | openai | groq` and set
`llm.model` accordingly (e.g. `claude-opus-4-8`, `gpt-4o`, `llama-3.3-70b-versatile`). Add the
provider's key to `.env` (none needed for `claude_code`). Add a new provider by implementing
`LLMProvider.generate` in [src/personal_agent/llm/](src/personal_agent/llm/) and registering it in
`factory.py`.
