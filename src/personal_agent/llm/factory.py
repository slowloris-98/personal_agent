"""Select and construct an LLM provider by name."""
from __future__ import annotations

from .base import LLMProvider


def get_provider(
    name: str, model: str, max_tokens: int = 4000, api_key: str | None = None
) -> LLMProvider:
    """Return an LLMProvider instance for `name`.

    Supported: claude_code | anthropic | openai | groq
    """
    name = (name or "").lower()
    if name == "claude_code":
        from .claude_code_provider import ClaudeCodeProvider

        return ClaudeCodeProvider(model=model, max_tokens=max_tokens)
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=model, max_tokens=max_tokens, api_key=api_key)
    if name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(model=model, max_tokens=max_tokens, api_key=api_key)
    if name == "groq":
        from .groq_provider import GroqProvider

        return GroqProvider(model=model, max_tokens=max_tokens, api_key=api_key)
    raise ValueError(
        f"Unknown LLM provider '{name}'. "
        "Choose one of: claude_code, anthropic, openai, groq."
    )
