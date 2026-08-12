from __future__ import annotations

from datetime import date, timedelta

from amelia_manager.metrics import calculate_metrics


def format_stats_report(repo, *, days: int, today: date | None = None) -> str:
    today = today or date.today()
    current_from = today - timedelta(days=days - 1)
    previous_to = current_from - timedelta(days=1)
    previous_from = previous_to - timedelta(days=days - 1)
    current = calculate_metrics(repo, date_from=current_from, date_to=today)
    previous = calculate_metrics(repo, date_from=previous_from, date_to=previous_to)
    dialogs = current["conversion"]["dialogs"]
    requests = current["conversion"]["admin_requests"]
    conversion = round(current["conversion"]["rate"] * 100)
    prev_conversion = round(previous["conversion"]["rate"] * 100)
    delta = conversion - prev_conversion
    escalations = round(current["escalations"]["rate"] * 100)
    dropoff = _most_common_dropoff(current["funnel"])
    return (
        f"Статистика за {days} дн.\n"
        f"Заявки: из {dialogs} обращений {requests} дошло до заявки ({conversion}%, {delta:+d} п.п. к прошлому периоду).\n"
        f"Эскалации: {escalations}%.\n"
        f"Чаще всего обрыв на шаге: {dropoff}."
    )


def _most_common_dropoff(funnel: dict[str, int]) -> str:
    if not funnel:
        return "данных пока нет"
    return min(funnel.items(), key=lambda item: item[1])[0]


def parse_stats_days(text: str, *, default: int = 7, maximum: int = 90) -> int:
    parts = text.strip().split()
    if len(parts) < 2:
        return default
    try:
        value = int(parts[1])
    except ValueError:
        return default
    return min(max(value, 1), maximum)
