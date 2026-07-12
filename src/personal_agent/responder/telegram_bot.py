"""Telegram responder — long-polls for your questions and answers from the store.

Long-polling (not webhooks) so it runs on the phone with no public URL. Read-only:
it looks things up in the phone-local store and replies; it never acts on your
behalf. Access is restricted to `responder.allowed_chat_ids` — messages from anyone
else are ignored silently.

Commands:
    /start, /help          show what the bot can do
    /model                 show the current answer LLM
    /model <provider> [m]  switch provider (anthropic|openai|ollama|groq), optional model

Run on the device:
    python -m personal_agent.responder.telegram_bot
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import requests

try:
    import telegramify_markdown
except ImportError:  # lib not installed on this device -> plain-text only
    telegramify_markdown = None

from .. import store
from ..config import Config, load_config
from ..llm import get_provider
from ..llm.base import LLMProvider
from .answer import answer_question

log = logging.getLogger(__name__)

_API = "https://api.telegram.org"
_MAX_MSG = 3500          # split raw text here; MarkdownV2 escaping grows length before the 4096 cap
_MAX_MSG_HARD = 4096     # Telegram's hard per-message limit (post-conversion)
_POLL_TIMEOUT = 30       # long-poll seconds
_SWITCHABLE = {"anthropic", "openai", "ollama", "groq", "claude_code"}

_HELP = (
    "👋 I'm your daily-planning assistant. Ask me about today's plan, your "
    "calendar, tasks, or recent emails — e.g. \"what's on my calendar?\", "
    "\"any urgent emails?\", \"what's my top priority?\".\n\n"
    "I'm read-only: I can look things up but can't send email or change tasks.\n\n"
    "Commands:\n"
    "• /help — this message\n"
    "• /model — show the current answer model\n"
    "• /model <provider> [model] — switch (anthropic, openai, ollama, groq)"
)


class TelegramClient:
    """Minimal Telegram Bot API wrapper over `requests` (session injectable)."""

    def __init__(self, token: str, session=None):
        self._base = f"{_API}/bot{token}"
        self._session = session or requests

    def get_updates(self, offset: int | None, timeout: int = _POLL_TIMEOUT) -> list[dict]:
        resp = self._session.get(
            f"{self._base}/getUpdates",
            params={"offset": offset, "timeout": timeout},
            timeout=timeout + 10,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])

    def send_message(self, chat_id: int, text: str) -> None:
        # The LLM emits GitHub-flavored Markdown. We translate each chunk to Telegram
        # MarkdownV2 so it renders; if conversion or the formatted send fails, we resend
        # that chunk as plain text so a reply is never lost.
        for chunk in _split(text, _MAX_MSG):
            if not self._send_chunk(chat_id, chunk, use_md=True):
                self._send_chunk(chat_id, chunk, use_md=False)

    def _send_chunk(self, chat_id: int, text: str, use_md: bool) -> bool:
        """Send one chunk. Returns False (without raising) when a MarkdownV2 attempt
        fails, signalling the caller to retry as plain text. A failed plain-text send
        raises, matching the previous guaranteed-delivery contract."""
        payload = {"chat_id": chat_id, "text": text}
        if use_md:
            if telegramify_markdown is None:
                return False
            try:
                converted = telegramify_markdown.markdownify(text)
            except Exception:  # noqa: BLE001 — any conversion error -> fall back to plain
                return False
            if len(converted) > _MAX_MSG_HARD:  # escaping pushed it past the hard cap
                return False
            payload["text"] = converted
            payload["parse_mode"] = "MarkdownV2"
        resp = self._session.post(
            f"{self._base}/sendMessage",
            json=payload,
            timeout=30,
        )
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            if use_md:  # bad MarkdownV2 (e.g. 400) -> let caller retry plain
                return False
            raise
        return True


def _split(text: str, limit: int) -> list[str]:
    """Split a long reply into <=limit chunks, preferring paragraph/line breaks."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > limit and current:
            chunks.append(current)
            current = ""
        # A single line longer than the limit is hard-split.
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current += line
    if current:
        chunks.append(current)
    return chunks


@dataclass
class BotState:
    conn: object
    config: Config
    provider: LLMProvider
    provider_name: str
    model: str
    allowed: set[int] = field(default_factory=set)


def _make_provider(config: Config, provider_name: str, model: str) -> LLMProvider:
    return get_provider(
        provider_name,
        model,
        max_tokens=config.llm.max_tokens,
        api_key=config.api_key_for_provider(provider_name),
    )


def _handle_model_command(state: BotState, text: str) -> str:
    parts = text.split()
    if len(parts) == 1:
        return f"Current answer model: *{state.provider_name}* / {state.model}"
    provider_name = parts[1].lower()
    if provider_name not in _SWITCHABLE:
        return (
            f"Unknown provider '{provider_name}'. "
            f"Choose one of: {', '.join(sorted(_SWITCHABLE))}."
        )
    model = parts[2] if len(parts) > 2 else state.model
    try:
        state.provider = _make_provider(state.config, provider_name, model)
    except Exception as exc:  # noqa: BLE001 — surface config errors to the user
        return f"Couldn't switch to {provider_name}: {exc}"
    state.provider_name, state.model = provider_name, model
    return f"Switched to *{provider_name}* / {model}."


def handle_message(state: BotState, chat_id: int, text: str) -> str | None:
    """Route one message to a reply. Returns None when nothing should be sent."""
    if state.allowed and chat_id not in state.allowed:
        log.warning("Ignoring message from unauthorized chat %s", chat_id)
        return None

    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("/start") or text.startswith("/help"):
        return _HELP
    if text.startswith("/model"):
        return _handle_model_command(state, text)

    try:
        return answer_question(state.conn, state.provider, str(chat_id), text)
    except Exception:  # noqa: BLE001 — one bad answer must not kill the loop
        log.exception("Failed to answer message from %s", chat_id)
        return "Sorry — I hit an error answering that. Please try again."


def run_bot(config: Config | None = None) -> None:
    """Long-poll Telegram and answer messages until interrupted."""
    config = config or load_config()
    if not config.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    conn = store.init_db(config.responder.db_path)
    state = BotState(
        conn=conn,
        config=config,
        provider=_make_provider(config, config.responder.provider, config.responder.model),
        provider_name=config.responder.provider,
        model=config.responder.model,
        allowed=set(config.responder.allowed_chat_ids),
    )
    client = TelegramClient(config.telegram_bot_token)
    log.info(
        "Responder bot up — provider=%s, allowed_chats=%d",
        state.provider_name, len(state.allowed),
    )

    offset: int | None = None
    while True:
        try:
            updates = client.get_updates(offset)
        except requests.RequestException as exc:
            log.warning("getUpdates failed, retrying: %s", exc)
            time.sleep(3)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message") or update.get("edited_message")
            if not msg or "text" not in msg:
                continue
            chat_id = msg["chat"]["id"]
            reply = handle_message(state, chat_id, msg["text"])
            if reply:
                try:
                    client.send_message(chat_id, reply)
                except requests.RequestException as exc:
                    log.warning("sendMessage to %s failed: %s", chat_id, exc)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_bot()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
