from __future__ import annotations

import pytest

from amelia_manager.company_profile import CompanyProfile, SheetsStockConfig, StockSourceConfig
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard
from amelia_manager.order_sheet import SheetsOrderAppender, append_order_to_sheet_if_needed, send_pending_sheet_rows
from amelia_manager.telegram_runtime import send_admin_order_request_if_ready


READY_PICKUP = OrderCard(
    budget=7500,
    colors=["розы"],
    fulfillment_type="pickup",
    delivery_date="2026-08-10",
    delivery_time="18:00",
    sender_name="Даниил",
    sender_phone="89990000001",
)


class CapturingTelegram:
    async def send_message(self, chat_id, text):
        return None


class FakeWorksheet:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.rows = []

    def append_row(self, values, value_input_option="USER_ENTERED"):
        if self.fail:
            raise RuntimeError("append failed")
        self.rows.append(values)


class FakeSheetsClient:
    def __init__(self, worksheet):
        self._worksheet = worksheet

    def open_by_key(self, spreadsheet_id):
        return self

    def worksheet(self, name):
        return self._worksheet


def profile() -> CompanyProfile:
    return CompanyProfile(
        company_name="Test Flowers",
        manager_name="Алина",
        business_type="florist",
        city="Калининград",
        tone="коротко",
        required_fields={},
        stock_source=StockSourceConfig(
            type="sheets",
            sheets=SheetsStockConfig(
                spreadsheet_id="sheet-1",
                assortment_sheet_name="Ассортимент",
                orders_sheet_name="Заказы",
                assortment_columns={},
                order_columns={"customer_name": "Имя", "budget": "Бюджет"},
            ),
        ),
    )


def test_order_card_has_sheet_row_written_flag():
    assert READY_PICKUP.sheet_row_written is False
    restored = OrderCard.from_dict({**READY_PICKUP.to_dict(), "sheet_row_written": True})
    assert restored.sheet_row_written is True


def test_sheets_order_appender_appends_order_id_service_columns_and_profile_fields():
    worksheet = FakeWorksheet()
    appender = SheetsOrderAppender(config=profile().stock_source.sheets, client=FakeSheetsClient(worksheet))

    appender.append_order(order_id=42, telegram_client="@dummy / 123", card=READY_PICKUP, created_at="2026-08-10 12:00:00")

    row = worksheet.rows[0]
    assert row[0] == 42
    assert "2026-08-10 12:00:00" in row
    assert "@dummy / 123" in row
    assert 7500 in row
    assert any("розы" in str(value) for value in row)


def test_append_order_to_sheet_marks_flag_only_after_success(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    db_client = repo.upsert_client(telegram_id=123, username="dummy")
    order = repo.get_or_create_active_order(client_id=db_client.id)
    repo.update_order_card(order_id=order.id, card=READY_PICKUP)
    order = repo.get_active_order(client_id=db_client.id)
    worksheet = FakeWorksheet()

    ok = append_order_to_sheet_if_needed(
        repo,
        order=order,
        client_label="@dummy / 123",
        company_profile=profile(),
        appender=SheetsOrderAppender(config=profile().stock_source.sheets, client=FakeSheetsClient(worksheet)),
    )

    assert ok is True
    assert repo.get_active_order(client_id=db_client.id).card.sheet_row_written is True


def test_append_order_to_sheet_keeps_flag_false_on_failure(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    db_client = repo.upsert_client(telegram_id=123, username="dummy")
    order = repo.get_or_create_active_order(client_id=db_client.id)
    repo.update_order_card(order_id=order.id, card=READY_PICKUP)
    order = repo.get_active_order(client_id=db_client.id)

    ok = append_order_to_sheet_if_needed(
        repo,
        order=order,
        client_label="@dummy / 123",
        company_profile=profile(),
        appender=SheetsOrderAppender(config=profile().stock_source.sheets, client=FakeSheetsClient(FakeWorksheet(fail=True))),
    )

    assert ok is False
    assert repo.get_active_order(client_id=db_client.id).card.sheet_row_written is False


@pytest.mark.asyncio
async def test_admin_send_also_appends_order_to_sheet_after_success(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    db_client = repo.upsert_client(telegram_id=123, username="dummy")
    order = repo.get_or_create_active_order(client_id=db_client.id)
    repo.update_order_card(order_id=order.id, card=READY_PICKUP)
    order = repo.get_active_order(client_id=db_client.id)
    worksheet = FakeWorksheet()

    sent = await send_admin_order_request_if_ready(
        CapturingTelegram(),
        repo=repo,
        order=order,
        admin_chat_id=999,
        client_label="@dummy / 123",
        company_profile=profile(),
        order_sheet_appender=SheetsOrderAppender(config=profile().stock_source.sheets, client=FakeSheetsClient(worksheet)),
    )

    assert sent is True
    assert repo.get_active_order(client_id=db_client.id).card.sheet_row_written is True
    assert worksheet.rows


def test_startup_retries_pending_sheet_rows(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    db_client = repo.upsert_client(telegram_id=123, username="dummy")
    order = repo.get_or_create_active_order(client_id=db_client.id)
    repo.update_order_card(
        order_id=order.id,
        card=OrderCard.from_dict({**READY_PICKUP.to_dict(), "admin_request_sent": True, "client_summary_sent": True}),
    )
    worksheet = FakeWorksheet()

    sent = send_pending_sheet_rows(
        repo,
        company_profile=profile(),
        appender=SheetsOrderAppender(config=profile().stock_source.sheets, client=FakeSheetsClient(worksheet)),
    )

    assert sent == 1
    assert repo.get_active_order(client_id=db_client.id).card.sheet_row_written is True
