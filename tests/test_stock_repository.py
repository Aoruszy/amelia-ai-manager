from datetime import date

from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.stock import StockItem, StockStatus


def test_repository_replaces_daily_stock_for_date(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    day = date(2026, 8, 8)

    repo.replace_daily_stock(
        stock_date=day,
        items=[
            StockItem(name="гортензия голубая", status=StockStatus.AVAILABLE, quantity_text="8", quantity_number=8),
            StockItem(name="пионы", status=StockStatus.UNAVAILABLE, quantity_text="нет", quantity_number=0),
        ],
        updated_by=598896543,
    )
    repo.replace_daily_stock(
        stock_date=day,
        items=[StockItem(name="розы белые", status=StockStatus.LOW, quantity_text="мало", quantity_number=None)],
        updated_by=598896543,
    )

    items = repo.list_daily_stock(stock_date=day)

    assert [(item.name, item.status, item.quantity_text) for item in items] == [
        ("розы белые", StockStatus.LOW, "мало")
    ]
