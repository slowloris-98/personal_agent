"""Anthropic (Claude) provider via the official SDK."""
from __future__ import annotations

from .base import LLMProvider


class AnthropicProvider(LLMProvider):
    def generate(self, system: str, user: str) -> str:
        import anthropic  # imported lazily so the dep is only needed when selected

        client = anthropic.Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Concatenate any text blocks in the response.
        return "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        ).strip()
