from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_MONTH_GENITIVE = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


def format_human_date(value: str | None, *, timezone_name: str = "Europe/Kaliningrad") -> str:
    if not value:
        return "не указано"
    relative = {"today": "сегодня", "tomorrow": "завтра"}.get(value)
    if relative:
        return relative
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return value
    today = _today_in_timezone(timezone_name)
    if parsed == today:
        return "сегодня"
    if parsed == today + timedelta(days=1):
        return "завтра"
    return f"{parsed.day} {_MONTH_GENITIVE[parsed.month]}"


def format_admin_date(value: str | None, *, timezone_name: str = "Europe/Kaliningrad") -> str:
    if not value:
        return "не указано"
    label = {"today": "сегодня", "tomorrow": "завтра"}.get(value, value)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return label
    if parsed < _today_in_timezone(timezone_name):
        return f"{label} ⚠️ дата в прошлом"
    return label


def _today_in_timezone(timezone_name: str) -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()
