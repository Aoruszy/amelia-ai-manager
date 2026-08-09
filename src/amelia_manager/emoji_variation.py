from __future__ import annotations

_EMOJIS = ["🙂", "☺️", "🌸", "💐", "✨", "👌", "😊"]


def vary_reply_emoji(text: str, seed: int) -> str:
    if "🙂" not in text:
        return text
    replacement = _EMOJIS[seed % len(_EMOJIS)]
    result = text.replace("🙂", replacement, 1)
    return result.replace("🙂", "")
