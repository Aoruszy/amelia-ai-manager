from __future__ import annotations

import re

_GREETING_ONLY_PATTERNS = (
    r"^здравствуйте[!.\s]*$",
    r"^добрый\s+(день|вечер|утро)[!.\s]*$",
    r"^привет[!.\s]*$",
    r"^доброго\s+(дня|вечера|утра)[!.\s]*$",
)


def is_greeting_only(text: str) -> bool:
    normalized = text.strip().lower().replace("ё", "е")
    if not normalized:
        return False
    return any(re.match(pattern, normalized) for pattern in _GREETING_ONLY_PATTERNS)
