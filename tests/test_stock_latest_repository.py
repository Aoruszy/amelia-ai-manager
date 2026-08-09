from datetime import date

from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.stock import StockItem, StockStatus


def test_repository_returns_latest_daily_stock_with_real_date(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    old_day = date(2026, 8, 7)
    latest_day = date(2026, 8, 8)
    repo.replace_daily_stock(
        stock_date=old_day,
        items=[StockItem(name="пионы", status=StockStatus.UNAVAILABLE, quantity_text="нет", quantity_number=0)],
        updated_by=1,
    )
    repo.replace_daily_stock(
        stock_date=latest_day,
        items=[StockItem(name="розы", status=StockStatus.AVAILABLE, quantity_text="10", quantity_number=10)],
        updated_by=1,
    )

    stock_date, items = repo.get_latest_daily_stock()

    assert stock_date == latest_day
    assert [item.name for item in items] == ["розы"]
