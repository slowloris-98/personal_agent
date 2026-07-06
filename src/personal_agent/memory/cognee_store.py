"""Cognee-backed memory store.

Cognee (https://docs.cognee.ai/) ingests text, builds a local knowledge graph
(entities, relationships, temporal awareness) and answers questions over it.
Defaults are fully local — SQLite (relational) + LanceDB (vector) +
Kuzu/NetworkX (graph) — but graph-building and querying use an LLM + embeddings,
here powered by OpenAI.

Cognee's public API (`add`, `cognify`, `search`) is async; this store bridges to
the synchronous pipeline with ``asyncio.run``. Every operation is wrapped so a
Cognee/network failure degrades gracefully and never breaks the daily run.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from ..models import ContextBundle
from .base import MemoryStore

log = logging.getLogger("personal_agent")


def build_memory_document(bundle: ContextBundle, plan: str) -> str:
    """Compact "plan + key facts" doc for one day.

    Key facts are derived directly from bundle fields (no raw email bodies) to
    keep the knowledge graph lean and low-noise.
    """
    lines: list[str] = [f"# Daily memory — {bundle.date} ({bundle.timezone})", ""]

    lines.append("## Plan")
    lines.append(plan.strip() or "(no plan generated)")
    lines.append("")

    lines.append("## Key facts")

    if bundle.events:
        for ev in bundle.events:
            when = "all day" if ev.all_day else f"{ev.start}–{ev.end}"
            lines.append(f"- Meeting on {bundle.date}: {ev.summary} ({when})")
    if bundle.tasks:
        for t in bundle.tasks:
            due = f" — due {t.due}" if t.due else ""
            lines.append(f"- Task: {t.title}{due}")
    if bundle.emails:
        for e in bundle.emails:
            lines.append(f"- Email [{e.account}] from {e.sender}: {e.subject}")
    if not (bundle.events or bundle.tasks or bundle.emails):
        lines.append("- (no calendar/task/email items recorded)")

    return "\n".join(lines)


def _stringify_results(results) -> str:
    """Coerce Cognee search results into one text block.

    ``cognee.search`` returns a list of ``SearchResult`` objects whose answer text
    lives in ``.search_result`` (itself a str or list). We also tolerate plain
    strings/dicts for forward/backward compatibility across versions.
    """
    if results is None:
        return ""
    if isinstance(results, str):
        return results.strip()
    if not isinstance(results, (list, tuple)):
        results = [results]

    parts: list[str] = []
    for r in results:
        if isinstance(r, str):
            parts.append(r)
        elif isinstance(r, dict):
            parts.append(str(r.get("search_result") or r.get("text") or r.get("content") or r))
        elif hasattr(r, "search_result"):
            sr = r.search_result
            parts.append(_stringify_results(sr) if not isinstance(sr, str) else sr)
        else:
            parts.append(str(r))
    return "\n".join(p for p in (s.strip() for s in parts) if p)


class CogneeMemoryStore(MemoryStore):
    def __init__(
        self,
        api_key: str,
        data_dir: Path,
        dataset_name: str = "personal_agent",
        retrieval_limit: int = 2000,
    ) -> None:
        self.dataset_name = dataset_name
        self.retrieval_limit = retrieval_limit
        self._configure(api_key, data_dir)

    # --- setup -----------------------------------------------------------------
    def _configure(self, api_key: str, data_dir: Path) -> None:
        """Point Cognee at a project-local data dir and supply the OpenAI key.

        Config surfaces vary across Cognee versions, so we set the documented env
        vars (which every version reads) and best-effort call the config helpers
        when present.
        """
        import cognee

        # OpenAI is Cognee's default LLM + embedding provider; the key drives both.
        os.environ.setdefault("LLM_API_KEY", api_key)
        os.environ.setdefault("EMBEDDING_API_KEY", api_key)
        # Single local user — skip Cognee's multi-tenant access control.
        os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")

        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "system").mkdir(parents=True, exist_ok=True)
        try:
            cognee.config.data_root_directory(str(data_dir / "data"))
            cognee.config.system_root_directory(str(data_dir / "system"))
        except Exception as exc:  # pragma: no cover - version-dependent surface
            log.warning("Could not set Cognee data directories: %s", exc)
        try:
            cognee.config.set_llm_api_key(api_key)
            cognee.config.set_embedding_api_key(api_key)
        except Exception:  # pragma: no cover - not present in all versions
            pass

    # --- async bridge ----------------------------------------------------------
    @staticmethod
    def _run(coro):
        return asyncio.run(coro)

    @staticmethod
    def _search_type():
        try:
            from cognee import SearchType
        except Exception:  # pragma: no cover - fallback for older layouts
            from cognee.modules.search.types import SearchType
        return SearchType

    # --- MemoryStore -----------------------------------------------------------
    def write(self, bundle: ContextBundle, plan: str) -> None:
        doc = build_memory_document(bundle, plan)
        try:
            self._run(self._write_async(doc))
            log.info("Wrote daily memory to Cognee dataset '%s'.", self.dataset_name)
        except Exception as exc:
            log.warning("Memory write failed (continuing): %s", exc)
            bundle.warnings.append(f"Memory write failed: {exc}")

    async def _write_async(self, doc: str) -> None:
        import cognee

        await cognee.add(doc, dataset_name=self.dataset_name)
        await cognee.cognify(datasets=[self.dataset_name])

    def retrieve_for_bundle(self, bundle: ContextBundle) -> str:
        query = self._bundle_query(bundle)
        if not query:
            return ""
        try:
            text = self._run(self._search_async(query))
        except Exception as exc:
            log.warning("Memory retrieval failed (continuing): %s", exc)
            bundle.warnings.append(f"Memory retrieval failed: {exc}")
            return ""
        return text[: self.retrieval_limit]

    def recall(self, question: str) -> str:
        try:
            return self._run(self._search_async(question)) or "No relevant memory found."
        except Exception as exc:
            log.warning("Memory recall failed: %s", exc)
            return f"Could not query memory: {exc}"

    def visualize(self, path: str) -> str:
        import cognee

        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._run(
                cognee.visualize_graph(
                    destination_file_path=path, dataset=self.dataset_name
                )
            )
            return path
        except Exception as exc:
            log.warning("Graph visualization failed: %s", exc)
            print(f"Could not export graph: {exc}")
            return ""

    def serve_ui(self) -> None:
        import cognee

        try:
            print("Launching Cognee UI (Ctrl+C to stop)...")
            cognee.start_ui(pid_callback=lambda _pid: None, open_browser=True)
        except Exception as exc:
            log.warning("Could not launch Cognee UI: %s", exc)
            print(f"Could not launch UI: {exc}")

    # --- helpers ---------------------------------------------------------------
    async def _search_async(self, query: str) -> str:
        import cognee

        search_type = self._search_type()
        results = await cognee.search(
            query_text=query, query_type=search_type.GRAPH_COMPLETION
        )
        return _stringify_results(results)

    @staticmethod
    def _bundle_query(bundle: ContextBundle) -> str:
        """Form a retrieval query from today's salient items."""
        bits: list[str] = []
        bits += [t.title for t in bundle.tasks]
        bits += [ev.summary for ev in bundle.events]
        bits += [e.subject for e in bundle.emails]
        bits = [b for b in bits if b]
        if not bits:
            return ""
        return (
            "Given today's tasks, meetings, and email subjects, what earlier "
            "commitments, decisions, or context from past days is relevant? "
            "Today's items: " + "; ".join(bits)
        )
