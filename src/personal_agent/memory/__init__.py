"""Memory layer: persistent knowledge-graph memory across days.

`get_memory_store` returns a Cognee-backed store when memory is enabled and an
OpenAI key is available, else a no-op `NullMemoryStore` so the daily run is
unaffected. Mirrors `llm.factory.get_provider`.
"""
from __future__ import annotations

import logging
import os

from ..config import MEMORY_DIR, Config
from .base import MemoryStore, NullMemoryStore

log = logging.getLogger("personal_agent")


def get_memory_store(config: Config) -> MemoryStore:
    mem = config.memory
    if not mem.enabled:
        return NullMemoryStore()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        log.warning("Memory enabled but OPENAI_API_KEY is not set; memory disabled.")
        return NullMemoryStore()

    try:
        from .cognee_store import CogneeMemoryStore

        return CogneeMemoryStore(
            api_key=api_key,
            data_dir=MEMORY_DIR,
            dataset_name=mem.dataset_name,
            retrieval_limit=mem.retrieval_limit,
        )
    except Exception as exc:
        log.warning("Could not initialize Cognee memory (%s); memory disabled.", exc)
        return NullMemoryStore()


__all__ = ["MemoryStore", "NullMemoryStore", "get_memory_store"]
