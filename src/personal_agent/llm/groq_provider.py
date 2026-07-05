"""Groq provider (OpenAI-compatible chat completions API)."""
from __future__ import annotations

from .base import LLMProvider


class GroqProvider(LLMProvider):
    def generate(self, system: str, user: str) -> str:
        from groq import Groq

        client = Groq(api_key=self.api_key)
        resp = client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()
