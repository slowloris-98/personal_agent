"""OpenAI provider via the official SDK (chat.completions)."""
from __future__ import annotations

from .base import LLMProvider


class OpenAIProvider(LLMProvider):
    def generate(self, system: str, user: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        resp = client.chat.completions.create(
            model=self.model,
            max_completion_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()
