from __future__ import annotations

from datetime import date, datetime, timezone

from amelia_manager.company_profile import SheetsStockConfig, StockSourceConfig, load_company_profile
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.stock import StockItem, StockStatus
from amelia_manager.stock_source import StockSnapshot
from amelia_manager.telegram_runtime import get_current_stock_snapshot, handle_stock_command
import amelia_manager.telegram_runtime as runtime_module


class FakeStockSource:
    def __init__(self):
        self.calls = 0

    def fetch(self):
        self.calls += 1
        return StockSnapshot(
            items=[StockItem(name="пионы", status=StockStatus.AVAILABLE, quantity_text="5", quantity_number=5, price=4500, unit="шт")],
            fetched_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
            source_name="fake",
        )


def test_get_current_stock_snapshot_uses_injected_source():
    source = FakeStockSource()

    snapshot = get_current_stock_snapshot(source)

    assert source.calls == 1
    assert snapshot.items[0].price == 4500


def test_handle_stock_command_mentions_override_for_sheets_profile(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    profile = load_company_profile("amelia_flowers")
    profile = type(profile)(
        **{
            **profile.__dict__,
            "stock_source": StockSourceConfig(
                type="sheets",
                sheets=SheetsStockConfig(
                    spreadsheet_id="sheet-1",
                    assortment_sheet_name="Ассортимент",
                    orders_sheet_name="Заказы",
                ),
            ),
        }
    )

    ack = handle_stock_command(
        repo,
        sender_id=598896543,
        text="/stock\nпионы — 5",
        today=date(2026, 8, 8),
        company_profile=profile,
    )

    assert "перекроет таблицу" in ack.lower()


def test_handle_stock_command_uses_company_profile_timezone_when_today_not_passed(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_module, "_today_in_timezone", lambda timezone_name: date(2026, 8, 13))
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    profile = load_company_profile("amelia_flowers")

    handle_stock_command(repo, sender_id=598896543, text="/stock\nпионы — 5", company_profile=profile)
    stock_date, items = repo.get_latest_daily_stock()

    assert stock_date == date(2026, 8, 13)
    assert items[0].name == "пионы"
