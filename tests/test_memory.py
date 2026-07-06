import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_agent import main as main_mod  # noqa: E402
from personal_agent.config import Account, Config, MemoryConfig  # noqa: E402
from personal_agent.llm.base import LLMProvider  # noqa: E402
from personal_agent.memory import get_memory_store  # noqa: E402
from personal_agent.memory.base import MemoryStore, NullMemoryStore  # noqa: E402
from personal_agent.memory.cognee_store import build_memory_document  # noqa: E402
from personal_agent.models import (  # noqa: E402
    CalendarEvent,
    ContextBundle,
    EmailItem,
    TaskItem,
)
from personal_agent.planner import build_user_prompt  # noqa: E402


class FakeMemoryStore(MemoryStore):
    def __init__(self):
        self.retrieved_for = None
        self.retrieve_count = 0
        self.written = None
        self.writes = []  # (date, plan) per write, in call order

    def retrieve_for_bundle(self, bundle):
        self.retrieved_for = bundle
        self.retrieve_count += 1
        return "PAST: you promised Boss a budget review last week."

    def write(self, bundle, plan):
        self.written = (bundle, plan)
        self.writes.append((bundle.date, plan))

    def recall(self, question):
        return f"answer to: {question}"


class FakeProvider(LLMProvider):
    def __init__(self):
        super().__init__(model="fake", max_tokens=10)
        self.last_user = None

    def generate(self, system: str, user: str) -> str:
        self.last_user = user
        return "### Top priorities\n- done"


def _bundle() -> ContextBundle:
    return ContextBundle(
        date="2026-07-04",
        timezone="Asia/Kolkata",
        emails=[EmailItem("acct1", "Boss <boss@x.com>", "Review budget", "Please review", "Fri")],
        events=[CalendarEvent("Standup", "2026-07-04T09:30:00+05:30", "2026-07-04T09:45:00+05:30")],
        tasks=[TaskItem("File taxes", due="2026-07-05")],
    )


# --- prompt rendering ------------------------------------------------------

def test_build_user_prompt_renders_memory_when_present():
    bundle = _bundle()
    bundle.memory = "PAST: budget review owed to Boss."
    prompt = build_user_prompt(bundle)
    assert "RELEVANT MEMORY / PAST CONTEXT" in prompt
    assert "budget review owed to Boss" in prompt


def test_build_user_prompt_omits_memory_when_empty():
    prompt = build_user_prompt(_bundle())  # memory defaults to ""
    assert "RELEVANT MEMORY" not in prompt


# --- key-facts document ----------------------------------------------------

def test_build_memory_document_has_plan_and_key_facts():
    doc = build_memory_document(_bundle(), "### Top priorities\n- ship it")
    assert "## Plan" in doc
    assert "ship it" in doc
    assert "## Key facts" in doc
    assert "Standup" in doc          # meeting
    assert "File taxes" in doc       # task
    assert "Review budget" in doc    # email subject
    assert "Please review" not in doc  # raw snippet excluded to keep graph lean


# --- factory degradation ---------------------------------------------------

def test_get_memory_store_null_when_disabled():
    cfg = Config(memory=MemoryConfig(enabled=False))
    assert isinstance(get_memory_store(cfg), NullMemoryStore)


def test_get_memory_store_null_when_no_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = Config(memory=MemoryConfig(enabled=True))
    assert isinstance(get_memory_store(cfg), NullMemoryStore)


def test_null_store_is_safe():
    store = NullMemoryStore()
    assert store.retrieve_for_bundle(_bundle()) == ""
    store.write(_bundle(), "plan")  # no-op, must not raise


# --- run() wiring ----------------------------------------------------------

def _fake_config() -> Config:
    return Config(accounts=[Account(label="acct1", primary=True)], memory=MemoryConfig())


def _patch_run(monkeypatch, store, provider):
    monkeypatch.setattr(main_mod, "load_config", _fake_config)
    monkeypatch.setattr(main_mod, "build_bundle", lambda config: _bundle())
    monkeypatch.setattr(main_mod, "get_memory_store", lambda config: store)
    monkeypatch.setattr(main_mod, "get_provider", lambda *a, **k: provider)
    monkeypatch.setattr(main_mod, "prepend_plan", lambda *a, **k: None)


def test_run_retrieves_before_plan_and_writes_after(monkeypatch):
    store, provider = FakeMemoryStore(), FakeProvider()
    _patch_run(monkeypatch, store, provider)

    assert main_mod.run(dry_run=False) == 0
    # retrieval happened and was injected into the prompt
    assert store.retrieved_for is not None
    assert "you promised Boss" in provider.last_user
    # memory was persisted on a real run
    assert store.written is not None
    assert store.written[1].startswith("### Top priorities")


def test_run_dry_run_skips_write(monkeypatch):
    store, provider = FakeMemoryStore(), FakeProvider()
    _patch_run(monkeypatch, store, provider)

    assert main_mod.run(dry_run=True) == 0
    assert store.retrieved_for is not None  # retrieval still happens
    assert store.written is None            # but nothing is persisted


def test_ask_prints_recall(monkeypatch, capsys):
    store = FakeMemoryStore()
    monkeypatch.setattr(main_mod, "load_config", lambda: Config(memory=MemoryConfig()))
    monkeypatch.setattr(main_mod, "get_memory_store", lambda config: store)

    assert main_mod.ask("what did I owe Boss?") == 0
    assert "answer to: what did I owe Boss?" in capsys.readouterr().out


# --- gmail relevance filter ------------------------------------------------

def test_compose_query_appends_filter():
    from personal_agent.collectors.gmail_collector import _compose_query
    assert _compose_query("newer_than:1d", "category:primary") == "newer_than:1d category:primary"
    assert _compose_query("newer_than:1d", "") == "newer_than:1d"
    assert _compose_query("", "category:primary") == "category:primary"


def test_dated_email_query_has_day_bounds_and_filter():
    from datetime import date
    q = main_mod._dated_email_query(date(2026, 6, 28), "category:primary")
    assert q == "after:2026/06/28 before:2026/06/29 category:primary"


# --- build_bundle_for_date -------------------------------------------------

def test_build_bundle_for_date_passes_query_and_omits_tasks(monkeypatch):
    from datetime import date

    captured = {}

    def fake_gmail(accounts, cfg, warnings, query=None, max_results=None):
        captured["query"] = query
        captured["max_results"] = max_results
        return []

    def fake_calendar(primary, cfg, warnings, on_date=None):
        captured["on_date"] = on_date
        return []

    def fake_tasks(primary, warnings):
        captured["tasks_called"] = True
        return []

    monkeypatch.setattr(main_mod.gmail_collector, "collect", fake_gmail)
    monkeypatch.setattr(main_mod.calendar_collector, "collect", fake_calendar)
    monkeypatch.setattr(main_mod.tasks_collector, "collect", fake_tasks)

    day = date(2026, 6, 28)
    bundle = main_mod.build_bundle_for_date(
        _fake_config(), day,
        email_query="after:2026/06/28 before:2026/06/29 category:primary",
        max_emails=40, include_tasks=False,
    )
    assert bundle.date == "2026-06-28"
    assert captured["query"].startswith("after:2026/06/28 before:2026/06/29")
    assert captured["max_results"] == 40
    assert captured["on_date"] == day
    assert "tasks_called" not in captured  # tasks skipped for backfill


# --- seed backfill ---------------------------------------------------------

def test_seed_writes_one_entry_per_day_oldest_first(monkeypatch):
    store, provider = FakeMemoryStore(), FakeProvider()
    prepend_calls = []

    monkeypatch.setattr(main_mod, "load_config", _fake_config)
    monkeypatch.setattr(main_mod, "get_memory_store", lambda config: store)
    monkeypatch.setattr(main_mod, "get_provider", lambda *a, **k: provider)
    monkeypatch.setattr(main_mod, "prepend_plan", lambda *a, **k: prepend_calls.append(a))
    # avoid hitting collectors: stub the per-day bundle build
    monkeypatch.setattr(
        main_mod, "build_bundle_for_date",
        lambda config, day, **kw: ContextBundle(date=day.strftime("%Y-%m-%d"), timezone="UTC"),
    )

    assert main_mod.seed(days=3) == 0
    assert len(store.writes) == 3               # one memory entry per day
    assert store.retrieve_count == 3            # retrieval before each write
    assert not prepend_calls                    # never touches the Google Doc
    dates = [d for d, _ in store.writes]
    assert dates == sorted(dates)               # oldest -> newest


def test_seed_errors_when_memory_disabled(monkeypatch, capsys):
    monkeypatch.setattr(main_mod, "load_config", _fake_config)
    monkeypatch.setattr(main_mod, "get_memory_store", lambda config: NullMemoryStore())

    assert main_mod.seed(days=3) == 1
    assert "Memory is disabled" in capsys.readouterr().out
