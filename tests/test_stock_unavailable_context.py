from amelia_manager.date_formatting import _today_in_timezone
from amelia_manager.stock import build_stock_context, parse_stock_text


def test_stock_context_includes_requested_unavailable_item_as_not_available():
    items = parse_stock_text("/stock\nпионы — нет\nрозы белые — есть")

    context = build_stock_context(items=items, colors=[], desired_text="Есть пионы?", stock_date=_today_in_timezone("Europe/Kaliningrad"))

    assert "пионы" in context
    assert "нет" in context
