from __future__ import annotations

import sqlite3
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from amelia_manager.stock import StockItem, StockStatus
from amelia_manager.order_card import OrderCard


@dataclass(frozen=True)
class ClientRecord:
    id: int
    telegram_id: int
    username: str | None
    stage: str
    summary: str


@dataclass(frozen=True)
class MessageRecord:
    id: int
    client_id: int
    direction: str
    text: str
    created_at: str


@dataclass(frozen=True)
class OrderRecord:
    id: int
    client_id: int
    status: str
    card: OrderCard
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class RetentionCleanupResult:
    deleted_messages: int = 0
    anonymized_orders: int = 0


def path_from_sqlite_url(database_url: str) -> Path:
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        return Path(database_url[len(prefix):])
    return Path(database_url)


class SQLiteRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL UNIQUE,
                    username TEXT,
                    stage TEXT NOT NULL DEFAULT 'new_lead',
                    summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER NOT NULL,
                    direction TEXT NOT NULL CHECK(direction IN ('in', 'out', 'admin')),
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(client_id) REFERENCES clients(id)
                );

                CREATE TABLE IF NOT EXISTS daily_stock (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_date TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    quantity_text TEXT NOT NULL,
                    quantity_number INTEGER,
                    updated_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    card_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(client_id) REFERENCES clients(id)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_client_id ON messages(client_id);
                CREATE INDEX IF NOT EXISTS idx_orders_client_status ON orders(client_id, status);
                """
            )

    def upsert_client(self, *, telegram_id: int, username: str | None) -> ClientRecord:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO clients (telegram_id, username)
                VALUES (?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = COALESCE(excluded.username, clients.username),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (telegram_id, username),
            )
        record = self.get_client_by_telegram_id(telegram_id)
        if record is None:
            raise RuntimeError("client upsert failed")
        return record

    def get_client_by_telegram_id(self, telegram_id: int) -> ClientRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, telegram_id, username, stage, summary FROM clients WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
        return self._client_from_row(row) if row else None

    def update_client_state(self, *, client_id: int, stage: str, summary: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE clients SET stage = ?, summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (stage, summary, client_id),
            )

    def add_message(self, *, client_id: int, direction: str, text: str) -> MessageRecord:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (client_id, direction, text) VALUES (?, ?, ?)",
                (client_id, direction, text),
            )
            message_id = int(cursor.lastrowid)
            row = conn.execute(
                "SELECT id, client_id, direction, text, created_at FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()
        return self._message_from_row(row)

    def list_messages(self, *, client_id: int, limit: int = 20, since_days: int | None = None) -> list[MessageRecord]:
        age_filter = ""
        params: tuple[object, ...]
        if since_days is not None:
            age_filter = "AND datetime(created_at) >= datetime('now', ?)"
            params = (client_id, f"-{since_days} days", limit)
        else:
            params = (client_id, limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, client_id, direction, text, created_at
                FROM (
                    SELECT id, client_id, direction, text, created_at
                    FROM messages
                    WHERE client_id = ?
                    {age_filter}
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
                """,
                params,
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def replace_daily_stock(self, *, stock_date: date, items: list[StockItem], updated_by: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM daily_stock WHERE stock_date = ?", (stock_date.isoformat(),))
            conn.executemany(
                """
                INSERT INTO daily_stock (stock_date, item_name, status, quantity_text, quantity_number, updated_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        stock_date.isoformat(),
                        item.name,
                        item.status.value,
                        item.quantity_text,
                        item.quantity_number,
                        updated_by,
                    )
                    for item in items
                ],
            )

    def list_daily_stock(self, *, stock_date: date) -> list[StockItem]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT item_name, status, quantity_text, quantity_number
                FROM daily_stock
                WHERE stock_date = ?
                ORDER BY id ASC
                """,
                (stock_date.isoformat(),),
            ).fetchall()
        return [
            StockItem(
                name=row["item_name"],
                status=StockStatus(row["status"]),
                quantity_text=row["quantity_text"],
                quantity_number=row["quantity_number"],
            )
            for row in rows
        ]

    def get_latest_daily_stock(self) -> tuple[date | None, list[StockItem]]:
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(stock_date) AS stock_date FROM daily_stock").fetchone()
        if row is None or row["stock_date"] is None:
            return None, []
        stock_date = date.fromisoformat(row["stock_date"])
        return stock_date, self.list_daily_stock(stock_date=stock_date)

    def list_active_orders_with_clients(self) -> list[tuple[OrderRecord, ClientRecord]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    o.id AS order_id,
                    o.client_id AS order_client_id,
                    o.status AS order_status,
                    o.card_json AS order_card_json,
                    o.created_at AS order_created_at,
                    o.updated_at AS order_updated_at,
                    c.id AS client_id,
                    c.telegram_id AS client_telegram_id,
                    c.username AS client_username,
                    c.stage AS client_stage,
                    c.summary AS client_summary
                FROM orders o
                JOIN clients c ON c.id = o.client_id
                WHERE o.status = 'active'
                ORDER BY o.id ASC
                """
            ).fetchall()
        return [
            (
                OrderRecord(
                    id=int(row["order_id"]),
                    client_id=int(row["order_client_id"]),
                    status=row["order_status"],
                    card=OrderCard.from_dict(json.loads(row["order_card_json"] or "{}")),
                    created_at=row["order_created_at"],
                    updated_at=row["order_updated_at"],
                ),
                ClientRecord(
                    id=int(row["client_id"]),
                    telegram_id=int(row["client_telegram_id"]),
                    username=row["client_username"],
                    stage=row["client_stage"],
                    summary=row["client_summary"],
                ),
            )
            for row in rows
        ]

    def get_active_order(self, *, client_id: int) -> OrderRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, client_id, status, card_json, created_at, updated_at
                FROM orders
                WHERE client_id = ? AND status = 'active'
                ORDER BY id DESC
                LIMIT 1
                """,
                (client_id,),
            ).fetchone()
        return self._order_from_row(row) if row else None

    def get_or_create_active_order(self, *, client_id: int) -> OrderRecord:
        existing = self.get_active_order(client_id=client_id)
        if existing:
            return existing
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO orders (client_id, status, card_json) VALUES (?, 'active', ?)",
                (client_id, json.dumps(OrderCard().to_dict(), ensure_ascii=False)),
            )
            order_id = int(cursor.lastrowid)
            row = conn.execute(
                "SELECT id, client_id, status, card_json, created_at, updated_at FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
        return self._order_from_row(row)

    def update_order_card(self, *, order_id: int, card: OrderCard) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE orders SET card_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(card.to_dict(), ensure_ascii=False), order_id),
            )

    def close_active_orders(self, *, client_id: int, status: str = "superseded") -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE client_id = ? AND status = 'active'",
                (status, client_id),
            )

    def cleanup_pii_older_than(
        self,
        *,
        retention_days: int,
        now: datetime | None = None,
    ) -> RetentionCleanupResult:
        """Delete old message history and anonymize PII in old completed orders."""
        if retention_days < 1:
            raise ValueError("retention_days must be >= 1")
        reference_time = now or datetime.now(timezone.utc)
        if reference_time.tzinfo is not None:
            reference_time = reference_time.astimezone(timezone.utc).replace(tzinfo=None)
        cutoff_text = (reference_time - timedelta(days=retention_days)).strftime("%Y-%m-%d %H:%M:%S")

        with self._connect() as conn:
            deleted_messages = conn.execute("DELETE FROM messages WHERE datetime(created_at) < datetime(?)", (cutoff_text,)).rowcount
            rows = conn.execute(
                """
                SELECT id, card_json
                FROM orders
                WHERE datetime(updated_at) < datetime(?)
                  AND (status != 'active'
                       OR json_extract(card_json, '$.admin_request_sent') = 1
                       OR json_extract(card_json, '$.client_summary_sent') = 1)
                """,
                (cutoff_text,),
            ).fetchall()
            anonymized_orders = 0
            for row in rows:
                card = OrderCard.from_dict(json.loads(row["card_json"] or "{}"))
                anonymized = _anonymize_order_card(card)
                if anonymized.to_dict() == card.to_dict():
                    continue
                conn.execute(
                    "UPDATE orders SET card_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (json.dumps(anonymized.to_dict(), ensure_ascii=False), row["id"]),
                )
                anonymized_orders += 1
        return RetentionCleanupResult(
            deleted_messages=max(deleted_messages, 0),
            anonymized_orders=anonymized_orders,
        )

    def delete_client_data_by_telegram_id(self, telegram_id: int) -> bool:
        """Delete one client's messages and orders for manual data-erasure requests."""
        client = self.get_client_by_telegram_id(telegram_id)
        if client is None:
            return False
        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE client_id = ?", (client.id,))
            conn.execute("DELETE FROM orders WHERE client_id = ?", (client.id,))
            conn.execute("DELETE FROM clients WHERE id = ?", (client.id,))
        return True

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _client_from_row(row: sqlite3.Row) -> ClientRecord:
        return ClientRecord(
            id=int(row["id"]),
            telegram_id=int(row["telegram_id"]),
            username=row["username"],
            stage=row["stage"],
            summary=row["summary"],
        )

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> MessageRecord:
        return MessageRecord(
            id=int(row["id"]),
            client_id=int(row["client_id"]),
            direction=row["direction"],
            text=row["text"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _order_from_row(row: sqlite3.Row) -> OrderRecord:
        return OrderRecord(
            id=int(row["id"]),
            client_id=int(row["client_id"]),
            status=row["status"],
            card=OrderCard.from_dict(json.loads(row["card_json"] or "{}")),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _anonymize_order_card(card: OrderCard) -> OrderCard:
    return OrderCard(
        occasion=card.occasion,
        budget=card.budget,
        colors=card.colors,
        forbidden_flowers=card.forbidden_flowers,
        fulfillment_type=card.fulfillment_type,
        delivery_date=card.delivery_date,
        delivery_time=card.delivery_time,
        address=None,
        sender_name=None,
        sender_phone=None,
        recipient_name=None,
        recipient_phone=None,
        payment_method=card.payment_method,
        postcard_text=None,
        anonymous=card.anonymous,
        photo_report_requested=card.photo_report_requested,
        custom_fields={},
        admin_request_sent=card.admin_request_sent,
        client_summary_sent=card.client_summary_sent,
    )
