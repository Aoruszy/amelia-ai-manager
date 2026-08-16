from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


from amelia_manager.company_profile import CompanyProfile, StockSourceConfig, SheetsStockConfig
from amelia_manager.date_formatting import _today_in_timezone
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.safety import check_reply_safety
import amelia_manager.stock as stock_module
from amelia_manager.stock import StockItem, StockStatus, build_stock_context, format_stock_ack, parse_stock_text
from amelia_manager.stock_source import ManualStockSource, SheetsStockSource


class FakeWorksheet:
    def __init__(self, rows=None, *, fail=False):
        self.rows = rows or []
        self.fail = fail
        self.calls = 0

    def get_all_records(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("sheets unavailable")
        return self.rows


class FakeSheetsClient:
    def __init__(self, worksheet):
        self._worksheet = worksheet

    def open_by_key(self, spreadsheet_id):
        return self

    def worksheet(self, name):
        return self._worksheet


def sheets_profile() -> CompanyProfile:
    return CompanyProfile(
        company_name="Test Flowers",
        manager_name="Алина",
        business_type="florist",
        city="Калининград",
        tone="коротко",
        stock_source=StockSourceConfig(
            type="sheets",
            sheets=SheetsStockConfig(
                spreadsheet_id="sheet-1",
                assortment_sheet_name="Ассортимент",
                orders_sheet_name="Заказы",
                assortment_columns={
                    "name": "название",
                    "quantity": "количество",
                    "price": "цена",
                    "status": "статус",
                    "note": "примечание",
                },
            ),
        ),
    )


def test_stock_item_supports_catalog_price_but_manual_stock_leaves_price_empty():
    items = parse_stock_text("/stock\nпионы — 10\nрозы — нет")

    assert items[0].price is None
    assert items[0].unit is None
    assert items[0].status == StockStatus.AVAILABLE


def test_build_stock_context_includes_known_price_shortly():
    context = build_stock_context(
        items=[StockItem(name="пионы", status=StockStatus.AVAILABLE, quantity_text="12", quantity_number=12, price=4500, unit="шт")],
        colors=[],
        desired_text="сколько стоят пионы?",
        stock_date=_today_in_timezone("Europe/Kaliningrad"),
    )

    assert "пионы" in context
    assert "4500 ₽/шт" in context


def test_build_stock_context_uses_profile_timezone_today(monkeypatch):
    monkeypatch.setattr(stock_module, "_today_in_timezone", lambda timezone_name: date(2026, 8, 14))

    context = build_stock_context(
        items=[StockItem(name="пионы", status=StockStatus.AVAILABLE, quantity_text="12", quantity_number=12)],
        colors=[],
        desired_text="пионы",
        stock_date=date(2026, 8, 14),
        timezone_name="Europe/Kaliningrad",
    )

    assert "устарело" not in context
    assert "пионы" in context


def test_sheets_stock_source_parses_rows_mirrors_to_sqlite_and_manual_source_reads_latest(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    worksheet = FakeWorksheet([
        {"название": " Пионы ", "количество": "12", "цена": "4 500 ₽", "статус": "", "примечание": ""},
        {"название": "Розы кустовые", "количество": "мало", "цена": "350", "статус": "", "примечание": ""},
        {"название": "", "количество": "5", "цена": "999"},
        {"название": "Гортензия", "количество": "нет", "цена": "", "статус": ""},
    ])

    snapshot = SheetsStockSource(
        repo,
        config=sheets_profile().stock_source.sheets,
        client=FakeSheetsClient(worksheet),
        now=lambda: datetime(2026, 8, 13, tzinfo=timezone.utc),
    ).fetch()

    assert [(item.name, item.quantity_text, item.price, item.status) for item in snapshot.items] == [
        ("пионы", "12", 4500, StockStatus.AVAILABLE),
        ("розы кустовые", "мало", 350, StockStatus.LOW),
        ("гортензия", "нет", None, StockStatus.UNAVAILABLE),
    ]
    assert snapshot.source_name == "google_sheets:Ассортимент"
    latest_date, latest_items = ManualStockSource(repo).fetch().fetched_at.date(), ManualStockSource(repo).fetch().items
    assert latest_date == date(2026, 8, 13)
    assert latest_items[0].price == 4500


def test_sheets_stock_source_mirrors_by_profile_timezone_day(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    worksheet = FakeWorksheet([{"название": "пионы", "количество": "10", "цена": "4500"}])

    snapshot = SheetsStockSource(
        repo,
        config=sheets_profile().stock_source.sheets,
        client=FakeSheetsClient(worksheet),
        now=lambda: datetime(2026, 8, 12, 22, 11, tzinfo=timezone.utc),
        timezone_name="Europe/Kaliningrad",
    ).fetch()

    latest_date, _ = repo.get_latest_daily_stock()
    assert snapshot.fetched_at.date() == date(2026, 8, 13)
    assert latest_date == date(2026, 8, 13)


def test_sheets_stock_source_falls_back_to_sqlite_when_api_unavailable(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    repo.replace_daily_stock(
        stock_date=date(2026, 8, 12),
        items=[StockItem(name="розы", status=StockStatus.AVAILABLE, quantity_text="7", quantity_number=7, price=300, unit="шт")],
        updated_by=1,
    )

    snapshot = SheetsStockSource(
        repo,
        config=sheets_profile().stock_source.sheets,
        client=FakeSheetsClient(FakeWorksheet(fail=True)),
    ).fetch()

    assert snapshot.source_name == "sqlite_fallback"
    assert snapshot.items[0].name == "розы"
    assert snapshot.items[0].price == 300


def test_sheets_stock_source_uses_ttl_cache(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    worksheet = FakeWorksheet([{"название": "пионы", "количество": "10", "цена": "4500"}])
    now = datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc)
    source = SheetsStockSource(
        repo,
        config=sheets_profile().stock_source.sheets,
        client=FakeSheetsClient(worksheet),
        ttl=timedelta(seconds=60),
        now=lambda: now,
    )

    first = source.fetch()
    second = source.fetch()

    assert first.items == second.items
    assert worksheet.calls == 1


def test_safety_rejects_catalog_price_not_supported_by_context():
    stock_context = "По наличию на сегодня релевантно:\n- пионы — 12, 4500 ₽/шт"

    assert check_reply_safety("Пионы стоят 4500 ₽ за штуку", stock_context=stock_context).is_safe
    result = check_reply_safety("Пионы стоят 5000 ₽ за штуку", stock_context=stock_context)
    assert not result.is_safe
    assert "unsupported_price_quote" in result.reasons


def test_safety_allows_bouquet_range_derived_from_catalog_price():
    stock_context = "По наличию на сегодня релевантно:\n- пионы — 12, 4500 ₽/шт"

    result = check_reply_safety("Букет выйдет примерно 4000–4500 ₽, итог подтвердит менеджер.", stock_context=stock_context)

    assert result.is_safe


def test_safety_allows_approximate_bouquet_range_without_catalog_exact_match():
    result = check_reply_safety("Такой букет обойдётся примерно в 4000–4500 ₽.")

    assert result.is_safe


def test_safety_allows_approximate_single_bouquet_estimate_without_catalog_exact_match():
    result = check_reply_safety("Букет выйдет около 4500 ₽.")

    assert result.is_safe


def test_safety_blocks_approximate_bouquet_estimate_above_profile_limit():
    profile = CompanyProfile(**{**sheets_profile().__dict__, "max_bouquet_estimate": 10000})

    result = check_reply_safety("Ориентировочно букет выйдет 12000 ₽.", company_profile=profile)

    assert not result.is_safe
    assert "unsupported_price_quote" in result.reasons


def test_safety_blocks_exact_bouquet_price_without_approximation_or_catalog():
    result = check_reply_safety("Такой букет обойдётся в 4500 ₽.")

    assert not result.is_safe
    assert "unsupported_price_quote" in result.reasons


def test_safety_allows_profile_prices_when_profile_is_passed():
    profile = sheets_profile()
    profile = CompanyProfile(**{**profile.__dict__, "delivery_city_price": 400, "free_delivery_from": 5000})

    result = check_reply_safety("Доставка стоит 400 ₽, от 5000 ₽ бесплатная.", company_profile=profile)

    assert result.is_safe


def test_stock_ack_mentions_manual_override_when_sheets_active():
    ack = format_stock_ack([StockItem(name="пионы", status=StockStatus.AVAILABLE, quantity_text="10")], source_type="sheets")

    assert "перекроет таблицу" in ack.lower()
    assert "до следующего успешного чтения" in ack.lower()
