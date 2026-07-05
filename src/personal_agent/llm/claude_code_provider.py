"""Claude Code provider: shells out to the local `claude` CLI (headless mode).

Uses your existing Claude Code subscription — no API key required. The user
prompt is piped via stdin (avoids OS command-line length limits); the system
prompt is passed with --append-system-prompt.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from .base import LLMProvider


class ClaudeCodeProvider(LLMProvider):
    def generate(self, system: str, user: str) -> str:
        # Allow override via env (e.g. full path to claude.cmd on Windows).
        cli = os.getenv("CLAUDE_CLI") or shutil.which("claude") or "claude"
        cmd = [
            cli,
            "-p",
            "--output-format",
            "text",
            "--append-system-prompt",
            system,
        ]
        result = subprocess.run(
            cmd,
            input=user,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
            shell=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"claude CLI failed (exit {result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result.stdout.strip()
