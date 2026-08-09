from __future__ import annotations


def split_into_telegram_messages(reply: str, max_messages: int = 3) -> list[str]:
    """Split an LLM reply into short natural Telegram messages."""
    parts = [part.strip() for part in reply.split("\n\n") if part.strip()]
    if not parts:
        return []
    return parts[:max_messages]
