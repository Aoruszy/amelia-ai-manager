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
    return _EMOJI_RE.sub("", reply).replace("  ", " ").strip()


def suppress_sensitive_tone_words(reply: str, forbidden_words: tuple[str, ...]) -> str:
    """Remove domain-forbidden tone words for sensitive occasions."""
    cleaned = suppress_emojis(reply)
    for word in forbidden_words:
        stem = word[:4]
        if not stem:
            continue
        cleaned = re.sub(rf"\b{re.escape(stem)}\w*\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.!?])", r"\1", cleaned)
    return cleaned.strip()
