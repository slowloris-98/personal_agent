"""Local on-device LLM via Ollama's HTTP API (no API key, fully offline).

The privacy/offline option for the responder. Point OLLAMA_HOST at the server if
it isn't the default localhost:11434. Answers are weaker/slower than the hosted
providers — treat this as opt-in, not the default (see plan's open considerations).
"""
from __future__ import annotations

import os

from .base import LLMProvider

_DEFAULT_HOST = "http://localhost:11434"
_TIMEOUT = 300  # seconds — local generation can be slow


class OllamaProvider(LLMProvider):
    def generate(self, system: str, user: str) -> str:
        import requests  # lazy: only needed when this provider is selected

        base = os.getenv("OLLAMA_HOST", _DEFAULT_HOST).rstrip("/")
        resp = requests.post(
            f"{base}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"num_predict": self.max_tokens},
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
