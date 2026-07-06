"""The memory-store contract: write, retrieve-for-plan, and ad-hoc recall.

A memory store persists past days (plans + key facts) and answers questions over
them, so the agent can reason about commitments and threads that span weeks or
months. It must never crash the daily run — implementations degrade to safe
no-ops/empty results on failure.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import ContextBundle


class MemoryStore(ABC):
    @abstractmethod
    def write(self, bundle: ContextBundle, plan: str) -> None:
        """Persist the day's plan plus key facts derived from the bundle."""
        raise NotImplementedError

    @abstractmethod
    def retrieve_for_bundle(self, bundle: ContextBundle) -> str:
        """Return relevant past context to inject into today's plan prompt.

        Returns "" when there is nothing relevant (or memory is unavailable).
        """
        raise NotImplementedError

    @abstractmethod
    def recall(self, question: str) -> str:
        """Answer an ad-hoc question from memory.

        Kept separate from any CLI so a future comms layer (text/WhatsApp) can
        call it directly.
        """
        raise NotImplementedError

    def visualize(self, path: str) -> str:
        """Export the memory graph to an HTML file; return the path (or "")."""
        print("Memory is disabled; nothing to visualize.")
        return ""

    def serve_ui(self) -> None:
        """Launch a local UI to browse the memory graph."""
        print("Memory is disabled; nothing to show.")


class NullMemoryStore(MemoryStore):
    """No-op store used when memory is disabled or no API key is configured.

    Keeps the rest of the pipeline unchanged: writes are dropped, retrieval and
    recall return empty/placeholder text.
    """

    def write(self, bundle: ContextBundle, plan: str) -> None:
        return None

    def retrieve_for_bundle(self, bundle: ContextBundle) -> str:
        return ""

    def recall(self, question: str) -> str:
        return "Memory is disabled. Enable it in config.yaml and set OPENAI_API_KEY to ask questions."
