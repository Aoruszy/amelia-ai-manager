from __future__ import annotations

import os
from typing import Any

from amelia_manager.company_profile import CompanyProfile, SheetsStockConfig
from amelia_manager.db.repository import OrderRecord, SQLiteRepository
from amelia_manager.order_card import OrderCard


class SheetsOrderAppender:
    def __init__(self, *, config: SheetsStockConfig, client: Any | None = None) -> None:
        self.config = config
        self.client = client

    def append_order(self, *, order_id: int, telegram_client: str, card: OrderCard, created_at: str) -> None:
        row = self._build_row(order_id=order_id, telegram_client=telegram_client, card=card, created_at=created_at)
        self._worksheet().append_row(row, value_input_option="USER_ENTERED")

    def _worksheet(self):
        client = self.client or _build_gspread_client()
        return client.open_by_key(self.config.spreadsheet_id).worksheet(self.config.orders_sheet_name)

    def _build_row(self, *, order_id: int, telegram_client: str, card: OrderCard, created_at: str) -> list[object]:
        service_values: list[object] = [
            order_id,
            created_at,
            telegram_client,
            "new",
            _card_summary(card),
        ]
        field_values = [_field_value(card, code) for code in self.config.order_columns]
        return service_values + field_values


def append_order_to_sheet_if_needed(
    repo: SQLiteRepository,
    *,
    order: OrderRecord,
    client_label: str,
    company_profile: CompanyProfile,
    appender: SheetsOrderAppender | None = None,
) -> bool:
    config = company_profile.stock_source.sheets
    if company_profile.stock_source.type != "sheets" or config is None:
        return False
    if order.card.sheet_row_written:
        return False
    actual_appender = appender or SheetsOrderAppender(config=config)
    try:
        actual_appender.append_order(
            order_id=order.id,
            telegram_client=client_label,
            card=order.card,
            created_at=order.created_at,
        )
    except Exception:  # noqa: BLE001 - SQLite remains source of truth; retry later
        return False
    repo.update_order_card(
        order_id=order.id,
        card=OrderCard.from_dict({**order.card.to_dict(), "sheet_row_written": True}),
    )
    return True


def send_pending_sheet_rows(
    repo: SQLiteRepository,
    *,
    company_profile: CompanyProfile,
    appender: SheetsOrderAppender | None = None,
) -> int:
    sent = 0
    for order, client in repo.list_active_orders_with_clients():
        if not order.card.admin_request_sent or order.card.sheet_row_written:
            continue
        client_label = f"@{client.username} / {client.telegram_id}" if client.username else str(client.telegram_id)
        if append_order_to_sheet_if_needed(
            repo,
            order=order,
            client_label=client_label,
            company_profile=company_profile,
            appender=appender,
        ):
            sent += 1
    return sent


def _field_value(card: OrderCard, code: str) -> object:
    mapping = {
        "budget": card.budget,
        "date": card.delivery_date,
        "time": card.delivery_time,
        "delivery_address": card.address,
        "address": card.address,
        "recipient_name": card.recipient_name,
        "recipient_phone": card.recipient_phone,
        "customer_name": card.sender_name,
        "sender_name": card.sender_name,
        "customer_phone": card.sender_phone,
        "sender_phone": card.sender_phone,
        "payment_method": card.payment_method,
        "product_preferences": ", ".join(card.colors),
    }
    return mapping.get(code, card.custom_fields.get(code, "")) or ""


def _card_summary(card: OrderCard) -> str:
    parts = []
    if card.colors:
        parts.append("пожелания: " + ", ".join(card.colors))
    if card.budget:
        parts.append(f"бюджет: {card.budget}")
    if card.fulfillment_type:
        parts.append(card.fulfillment_type)
    if card.delivery_date or card.delivery_time:
        parts.append(" ".join(part for part in [card.delivery_date, card.delivery_time] if part))
    return "; ".join(parts)


def _build_gspread_client():
    try:
        import gspread
    except ImportError as exc:  # pragma: no cover - production config only
        raise RuntimeError("gspread is required for Google Sheets order export") from exc
    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not service_account_file:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE is required for Google Sheets order export")
    return gspread.service_account(filename=service_account_file)
