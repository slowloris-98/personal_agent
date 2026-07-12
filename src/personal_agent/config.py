"""Configuration loading: config.yaml (structure) + .env (secrets)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Project root = two levels up from this file (src/personal_agent/config.py -> project/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"
LOGS_DIR = PROJECT_ROOT / "logs"
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass
class Account:
    label: str
    primary: bool = False
    # How this account is labelled in the plan (e.g. "Personal", "Work"). The
    # `label` stays the stable token-file key; `name` is display-only.
    name: str = ""

    @property
    def display_name(self) -> str:
        return self.name or self.label


@dataclass
class CollectConfig:
    email_query: str = "newer_than:1d"
    max_emails_per_account: int = 30
    calendar_id: str = "primary"
    timezone: str = "UTC"


@dataclass
class OutputConfig:
    # Where plans are written: "google_docs" (one Doc per day, native Markdown
    # import) or "notion" (root page -> weekly subpages -> per-day subpages).
    target: str = "google_docs"
    # google_docs: name of the Drive folder (created and owned by the agent)
    # that holds the auto-created per-day plan Docs.
    folder_name: str = "Daily Plans"
    # google_docs (optional): id of a specific Drive folder to write into. When
    # set it takes precedence over folder_name. Under the narrow drive.file scope
    # this only works for a folder this app created (or was explicitly granted);
    # leave blank to let the agent create/own the folder_name folder instead.
    folder_id: str = ""
    # notion: id of the "Daily Planning" page shared with the integration; new
    # weekly/day subpages are created under it. The API token lives in .env.
    notion_root_page_id: str = ""


@dataclass
class LLMConfig:
    provider: str = "claude_code"
    model: str = "claude-opus-4-8"
    max_tokens: int = 4000


@dataclass
class ResponderConfig:
    """The 24/7 communication layer: the PC pushes here, the phone answers from it.

    Off by default so existing runs are unaffected. When `enabled`, the daily run
    pushes each day's plan + emails to the phone's ingest endpoint (`ingest_host`)
    over Tailscale. `provider`/`model` pick the (switchable) LLM the phone uses to
    answer — independent of the heavier `llm` provider used to generate the plan.
    """
    enabled: bool = False
    ingest_host: str = ""            # PC -> phone push target, e.g. "phone-ts:8000"
    db_path: str = "data/agent.db"   # phone-local SQLite (source of truth)
    retention_days: int = 60
    provider: str = "anthropic"      # anthropic | openai | ollama  (switchable)
    model: str = "claude-haiku-4-5-20251001"
    allowed_chat_ids: list[int] = field(default_factory=list)


@dataclass
class Config:
    accounts: list[Account] = field(default_factory=list)
    collect: CollectConfig = field(default_factory=CollectConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    responder: ResponderConfig = field(default_factory=ResponderConfig)

    @property
    def primary_account(self) -> Account:
        for acct in self.accounts:
            if acct.primary:
                return acct
        if self.accounts:
            return self.accounts[0]
        raise ValueError("No accounts configured in config.yaml")

    def api_key_for_provider(self, provider: str | None = None) -> str | None:
        """Return the API key for `provider` (defaults to the daily `llm` provider).

        Pass an explicit provider (e.g. the responder's) to resolve its key. Returns
        None for providers that need no key (e.g. claude_code, ollama).
        """
        provider = provider or self.llm.provider
        env_var = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "groq": "GROQ_API_KEY",
        }.get(provider)
        return os.getenv(env_var) if env_var else None

    @property
    def notion_token(self) -> str | None:
        """The Notion integration token from the environment (NOTION_API_KEY)."""
        return os.getenv("NOTION_API_KEY")

    @property
    def ingest_token(self) -> str | None:
        """Shared PC<->phone bearer secret for the ingest endpoint (INGEST_TOKEN)."""
        return os.getenv("INGEST_TOKEN")

    @property
    def telegram_bot_token(self) -> str | None:
        """The Telegram bot token from the environment (TELEGRAM_BOT_TOKEN)."""
        return os.getenv("TELEGRAM_BOT_TOKEN")


def load_config(path: Path | None = None) -> Config:
    """Load .env (secrets) and config.yaml (structure) into a Config."""
    load_dotenv(PROJECT_ROOT / ".env")

    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    accounts = [
        Account(
            label=a["label"],
            primary=bool(a.get("primary", False)),
            name=a.get("name", ""),
        )
        for a in raw.get("accounts", [])
    ]
    collect = CollectConfig(**{**CollectConfig().__dict__, **raw.get("collect", {})})
    output = OutputConfig(**{**OutputConfig().__dict__, **raw.get("output", {})})
    llm = LLMConfig(**{**LLMConfig().__dict__, **raw.get("llm", {})})
    responder = ResponderConfig(
        **{**ResponderConfig().__dict__, **raw.get("responder", {})}
    )

    return Config(
        accounts=accounts, collect=collect, output=output, llm=llm, responder=responder
    )
