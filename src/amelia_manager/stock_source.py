from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from amelia_manager.company_profile import SheetsStockConfig
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.stock import StockItem, StockStatus, _extract_quantity_number, _status_from_quantity


@dataclass(frozen=True)
class StockSnapshot:
    items: list[StockItem]
    fetched_at: datetime
    source_name: str


class StockSource(Protocol):
    def fetch(self) -> StockSnapshot: ...


class ManualStockSource:
    def __init__(self, repo: SQLiteRepository) -> None:
        self.repo = repo

    def fetch(self) -> StockSnapshot:
        stock_date, items = self.repo.get_latest_daily_stock()
        fetched_at = _datetime_from_date(stock_date) if stock_date else datetime.now(timezone.utc)
        return StockSnapshot(items=items, fetched_at=fetched_at, source_name="manual")


class SheetsStockSource:
    def __init__(
        self,
        repo: SQLiteRepository,
        *,
        config: SheetsStockConfig,
        client: Any | None = None,
        ttl: timedelta = timedelta(seconds=60),
        now=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.repo = repo
        self.config = config
        self.client = client
        self.ttl = ttl
        self.now = now
        self._cached: StockSnapshot | None = None

    def fetch(self) -> StockSnapshot:
        current = self.now()
        if self._cached and current - self._cached.fetched_at < self.ttl:
            return self._cached
        try:
            rows = self._worksheet().get_all_records()
            items = parse_sheets_stock_rows(rows, columns=self.config.assortment_columns)
            snapshot = StockSnapshot(
                items=items,
                fetched_at=current,
                source_name=f"google_sheets:{self.config.assortment_sheet_name}",
            )
            self.repo.replace_daily_stock(stock_date=current.date(), items=items, updated_by=0)
            self._cached = snapshot
            return snapshot
        except Exception:  # noqa: BLE001 - stock must degrade, never break dialogue
            stock_date, items = self.repo.get_latest_daily_stock()
            return StockSnapshot(
                items=items,
                fetched_at=_datetime_from_date(stock_date) if stock_date else current,
                source_name="sqlite_fallback",
            )

    def _worksheet(self):
        client = self.client or _build_gspread_client()
        return client.open_by_key(self.config.spreadsheet_id).worksheet(self.config.assortment_sheet_name)


def parse_sheets_stock_rows(rows: list[dict[str, Any]], *, columns: dict[str, str]) -> list[StockItem]:
    result: list[StockItem] = []
    name_col = columns.get("name", "название")
    quantity_col = columns.get("quantity", "количество")
    price_col = columns.get("price", "цена")
    status_col = columns.get("status", "статус")
    unit_col = columns.get("unit", "единица")
    for row in rows:
        name = _clean_text(row.get(name_col)).lower()
        if not name:
            continue
        quantity_text = _clean_text(row.get(quantity_col)).lower()
        status_text = _clean_text(row.get(status_col)).lower()
        quantity_number = _extract_quantity_number(quantity_text)
        status = _status_from_quantity(status_text or quantity_text, quantity_number)
        result.append(
            StockItem(
                name=name,
                status=status,
                quantity_text=quantity_text or status_text or "есть",
                quantity_number=0 if status == StockStatus.UNAVAILABLE else quantity_number,
                price=_parse_price(row.get(price_col)),
                unit=_clean_text(row.get(unit_col)).lower() or "шт",
            )
        )
    return result


def _parse_price(value: Any) -> int | None:
    text = _clean_text(value)
    if not text:
        return None
    digits = re.sub(r"\D+", "", text)
    return int(digits) if digits else None


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _datetime_from_date(value: date | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)


def _build_gspread_client():
    try:
        import gspread
    except ImportError as exc:  # pragma: no cover - exercised only in production config errors
        raise RuntimeError("gspread is required for Google Sheets stock source") from exc
    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not service_account_file:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE is required for Google Sheets stock source")
    return gspread.service_account(filename=service_account_file)
