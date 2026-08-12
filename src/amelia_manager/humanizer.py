from __future__ import annotations

import re


_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\ufe0f]+")


def split_into_telegram_messages(reply: str, max_messages: int = 3) -> list[str]:
    """Split an LLM reply into short natural Telegram messages."""
    parts = [part.strip() for part in reply.split("\n\n") if part.strip()]
    if not parts:
        return []
    return parts[:max_messages]


def suppress_emojis(reply: str) -> str:
    """Remove emoji for sensitive occasions where decorative tone is unsafe."""
    cleaned = _EMOJI_RE.sub("", reply)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()
