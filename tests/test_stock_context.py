from datetime import date, timedelta

from amelia_manager.date_formatting import _today_in_timezone
from amelia_manager.stock import StockItem, StockStatus, build_stock_context


def test_build_stock_context_matches_color_and_flower_request():
    context = build_stock_context(
        items=[
            StockItem(name="гортензия голубая", status=StockStatus.AVAILABLE, quantity_text="8", quantity_number=8),
            StockItem(name="пионы", status=StockStatus.UNAVAILABLE, quantity_text="нет", quantity_number=0),
            StockItem(name="розы белые", status=StockStatus.LOW, quantity_text="мало", quantity_number=None),
        ],
        colors=["голубой", "белый"],
        desired_text="хочу букет с гортензией",
        stock_date=_today_in_timezone("Europe/Kaliningrad"),
    )

    assert "По наличию на сегодня" in context
    assert "гортензия голубая — 8" in context
    assert "розы белые — мало" in context
    assert "пионы" not in context


def test_build_stock_context_warns_when_stock_is_stale_or_empty():
    assert "наличие на сегодня не внесено" in build_stock_context(
        items=[], colors=[], desired_text="", stock_date=None
    )
    assert "устарело" in build_stock_context(
        items=[StockItem(name="розы", status=StockStatus.AVAILABLE, quantity_text="есть")],
        colors=[],
        desired_text="розы",
        stock_date=_today_in_timezone("Europe/Kaliningrad") - timedelta(days=1),
    )
