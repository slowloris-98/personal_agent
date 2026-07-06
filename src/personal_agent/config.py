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
MEMORY_DIR = PROJECT_ROOT / "memory_store"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass
class Account:
    label: str
    primary: bool = False


@dataclass
class CollectConfig:
    email_query: str = "newer_than:1d"
    email_filter: str = ""          # Gmail operators appended to scope to relevant mail (e.g. "category:primary")
    max_emails_per_account: int = 30
    calendar_id: str = "primary"
    timezone: str = "UTC"


@dataclass
class OutputConfig:
    doc_id: str = ""


@dataclass
class LLMConfig:
    provider: str = "claude_code"
    model: str = "claude-opus-4-8"
    max_tokens: int = 4000


@dataclass
class MemoryConfig:
    """Persistent knowledge-graph memory (Cognee). Powered by OpenAI."""
    enabled: bool = False
    provider: str = "openai"        # Cognee LLM/embedding backend
    dataset_name: str = "personal_agent"
    retrieval_limit: int = 2000     # max chars of retrieved context injected into the plan


@dataclass
class Config:
    accounts: list[Account] = field(default_factory=list)
    collect: CollectConfig = field(default_factory=CollectConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)

    @property
    def primary_account(self) -> Account:
        for acct in self.accounts:
            if acct.primary:
                return acct
        if self.accounts:
            return self.accounts[0]
        raise ValueError("No accounts configured in config.yaml")

    def api_key_for_provider(self) -> str | None:
        """Return the API key for the configured provider from the environment.

        Returns None for providers that need no key (e.g. claude_code).
        """
        env_var = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "groq": "GROQ_API_KEY",
        }.get(self.llm.provider)
        return os.getenv(env_var) if env_var else None


def load_config(path: Path | None = None) -> Config:
    """Load .env (secrets) and config.yaml (structure) into a Config."""
    load_dotenv(PROJECT_ROOT / ".env")

    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    accounts = [
        Account(label=a["label"], primary=bool(a.get("primary", False)))
        for a in raw.get("accounts", [])
    ]
    collect = CollectConfig(**{**CollectConfig().__dict__, **raw.get("collect", {})})
    output = OutputConfig(**{**OutputConfig().__dict__, **raw.get("output", {})})
    llm = LLMConfig(**{**LLMConfig().__dict__, **raw.get("llm", {})})
    memory = MemoryConfig(**{**MemoryConfig().__dict__, **raw.get("memory", {})})

    return Config(
        accounts=accounts, collect=collect, output=output, llm=llm, memory=memory
    )
