from datetime import date

from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.telegram_runtime import handle_stock_command, is_stock_command


def test_is_stock_command():
    assert is_stock_command("/stock\nрозы - есть") is True
    assert is_stock_command("Наличие на сегодня:\nрозы - есть") is True
    assert is_stock_command("розы - есть") is False


def test_handle_stock_command_saves_items_and_returns_ack(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()

    ack = handle_stock_command(
        repo,
        sender_id=598896543,
        text="/stock\nгортензия голубая — 8\nпионы — нет",
        today=date(2026, 8, 8),
    )

    items = repo.list_daily_stock(stock_date=date(2026, 8, 8))
    assert "Приняла наличие на сегодня" in ack
    assert [item.name for item in items] == ["гортензия голубая", "пионы"]
