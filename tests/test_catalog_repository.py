from datetime import date

from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.stock import StockItem, StockStatus
from amelia_manager.stock_source import DbCatalogStockSource


def test_initialize_migrates_latest_daily_stock_to_catalog_idempotently(tmp_path):
    repo = SQLiteRepository(tmp_path / "catalog.sqlite3")
    repo.initialize()
    repo.replace_daily_stock(
        stock_date=date(2026, 8, 12),
        items=[StockItem("пионы", StockStatus.UNAVAILABLE, "нет", 0, 4500, "шт")],
        updated_by=1,
    )
    repo.replace_daily_stock(
        stock_date=date(2026, 8, 13),
        items=[StockItem("пионы", StockStatus.AVAILABLE, "12", 12, 4500, "шт")],
        updated_by=2,
    )

    repo.initialize()
    repo.initialize()

    items = repo.list_catalog_items(include_inactive=True)
    assert len(items) == 1
    assert items[0].name == "пионы"
    assert items[0].quantity_number == 12
    assert items[0].price == 4500


def test_catalog_updates_write_daily_stock_journal_and_db_source_reads_active(tmp_path):
    repo = SQLiteRepository(tmp_path / "catalog.sqlite3")
    repo.initialize()

    item = repo.upsert_catalog_item(name="Пионы", quantity_number=3, price=4500, unit="шт", updated_by=42)
    repo.update_catalog_item(item.id, quantity_number=0, updated_by=42)
    repo.update_catalog_item(item.id, is_active=False, updated_by=42)

    assert DbCatalogStockSource(repo).fetch().items == []
    latest_date, journal_items = repo.get_latest_daily_stock()
    assert latest_date is not None
    assert journal_items[-1].name == "Пионы"
    assert journal_items[-1].status == StockStatus.UNAVAILABLE
    assert len(repo.list_catalog_items(include_inactive=True)) == 1


def test_catalog_name_is_unique_case_insensitive(tmp_path):
    repo = SQLiteRepository(tmp_path / "catalog.sqlite3")
    repo.initialize()

    first = repo.upsert_catalog_item(name="Пионы", quantity_number=5, price=4500, unit="шт", updated_by=1)
    second = repo.upsert_catalog_item(name="пионы", quantity_number=1, price=4300, unit="шт", updated_by=2)

    assert first.id == second.id
    assert second.quantity_number == 1
    assert len(repo.list_catalog_items(include_inactive=True)) == 1
