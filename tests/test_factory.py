import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_agent.llm import get_provider  # noqa: E402
from personal_agent.llm.anthropic_provider import AnthropicProvider  # noqa: E402
from personal_agent.llm.claude_code_provider import ClaudeCodeProvider  # noqa: E402
from personal_agent.llm.groq_provider import GroqProvider  # noqa: E402
from personal_agent.llm.openai_provider import OpenAIProvider  # noqa: E402


@pytest.mark.parametrize(
    "name,cls",
    [
        ("claude_code", ClaudeCodeProvider),
        ("anthropic", AnthropicProvider),
        ("openai", OpenAIProvider),
        ("groq", GroqProvider),
        ("CLAUDE_CODE", ClaudeCodeProvider),  # case-insensitive
    ],
)
def test_get_provider_selects_correct_class(name, cls):
    provider = get_provider(name, model="m", max_tokens=10, api_key="k")
    assert isinstance(provider, cls)
    assert provider.model == "m"
    assert provider.max_tokens == 10


def test_get_provider_unknown_raises():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_provider("does-not-exist", model="m")
