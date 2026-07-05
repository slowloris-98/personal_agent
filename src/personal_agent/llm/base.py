"""The LLM provider contract. One method: generate(system, user) -> str."""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    def __init__(self, model: str, max_tokens: int = 4000, api_key: str | None = None):
        self.model = model
        self.max_tokens = max_tokens
        self.api_key = api_key

    @abstractmethod
    def generate(self, system: str, user: str) -> str:
        """Return the model's text completion for the given system + user prompts."""
        raise NotImplementedError
