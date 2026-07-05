import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_agent.llm.base import LLMProvider  # noqa: E402
from personal_agent.models import (  # noqa: E402
    CalendarEvent,
    ContextBundle,
    EmailItem,
    TaskItem,
)
from personal_agent.planner import build_user_prompt, generate_plan  # noqa: E402


class FakeProvider(LLMProvider):
    def __init__(self):
        super().__init__(model="fake", max_tokens=10)
        self.last_system = None
        self.last_user = None

    def generate(self, system: str, user: str) -> str:
        self.last_system = system
        self.last_user = user
        return "### Top priorities\n- done"


def _bundle() -> ContextBundle:
    return ContextBundle(
        date="2026-07-04",
        timezone="Asia/Kolkata",
        emails=[
            EmailItem("acct1", "Boss <boss@x.com>", "Review budget", "Please review", "Fri"),
        ],
        events=[
            CalendarEvent("Standup", "2026-07-04T09:30:00+05:30", "2026-07-04T09:45:00+05:30"),
        ],
        tasks=[TaskItem("File taxes", due="2026-07-05")],
    )


def test_build_user_prompt_includes_all_sections():
    prompt = build_user_prompt(_bundle())
    assert "TODAY'S CALENDAR EVENTS" in prompt
    assert "OPEN TASKS" in prompt
    assert "EMAILS (last 24h)" in prompt
    assert "Review budget" in prompt
    assert "[acct1]" in prompt
    assert "Standup" in prompt
    assert "File taxes" in prompt


def test_build_user_prompt_handles_empty_bundle():
    empty = ContextBundle(date="2026-07-04", timezone="UTC")
    prompt = build_user_prompt(empty)
    assert prompt.count("(none)") == 3


def test_generate_plan_passes_prompts_to_provider():
    provider = FakeProvider()
    result = generate_plan(_bundle(), provider)
    assert result.startswith("### Top priorities")
    assert "personal" in provider.last_system.lower()
    assert "Review budget" in provider.last_user
