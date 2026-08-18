from __future__ import annotations

import sqlite3
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from amelia_manager.events import EventName
from amelia_manager.observability import sanitize_payload
from amelia_manager.stock import StockItem, StockStatus
from amelia_manager.order_card import OrderCard

ORDER_STATUSES = ("draft", "submitted", "confirmed", "in_production", "ready", "fulfilled", "cancelled")
ACTIVE_ORDER_STATUSES = ("draft", "submitted", "confirmed", "in_production", "ready", "active")
TERMINAL_ORDER_STATUSES = ("fulfilled", "cancelled", "superseded", "completed")


@dataclass(frozen=True)
class CatalogItemRecord:
    id: int
    name: str
    status: StockStatus
    quantity_text: str
    quantity_number: int | None
    price: int | None
    unit: str | None
    is_active: bool
    sort_order: int
    updated_by: int | None
    updated_at: str
    created_at: str


@dataclass(frozen=True)
class ClientRecord:
    id: int
    telegram_id: int
    username: str | None
    stage: str
    summary: str
    opted_out_at: str | None = None
    bot_paused_at: str | None = None
    paused_by: str | None = None


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
    deleted_events: int = 0


@dataclass(frozen=True)
class EventRecord:
    id: int
    client_id: int
    order_id: int | None
    event: str
    payload_json: str
    created_at: str


@dataclass(frozen=True)
class OutboundRecord:
    id: int
    client_id: int
    order_id: int | None
    kind: str
    scheduled_at: str
    sent_at: str | None
    cancelled_at: str | None
    attempt_count: int
    created_at: str


@dataclass(frozen=True)
class DialogueRecord:
    client: ClientRecord
    active_order: OrderRecord | None
    last_message_at: str | None
    last_message_text: str | None


_PHONE_DIGITS_SQL = (
    "replace(replace(replace(replace(replace("
    "COALESCE(json_extract(so.card_json, '$.{field}'), '')"
    ", ' ', ''), '+', ''), '-', ''), '(', ''), ')', '')"
)


def _pylower(value: object) -> str:
    # ё→е как везде в проекте: иначе «петр» не найдёт «Пётр».
    return str(value).lower().replace("ё", "е") if value is not None else ""


def _digits_only(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


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
                    opted_out_at TEXT,
                    bot_paused_at TEXT,
                    paused_by TEXT,
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
                    price INTEGER,
                    unit TEXT,
                    updated_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS catalog_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    quantity_number INTEGER,
                    quantity_text TEXT NOT NULL,
                    price INTEGER,
                    unit TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    updated_by INTEGER,
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

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER NOT NULL,
                    order_id INTEGER,
                    event TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(client_id) REFERENCES clients(id),
                    FOREIGN KEY(order_id) REFERENCES orders(id)
                );

                CREATE TABLE IF NOT EXISTS outbound (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER NOT NULL,
                    order_id INTEGER,
                    kind TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    sent_at TEXT,
                    cancelled_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(client_id) REFERENCES clients(id),
                    FOREIGN KEY(order_id) REFERENCES orders(id)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_client_id ON messages(client_id);
                CREATE INDEX IF NOT EXISTS idx_orders_client_status ON orders(client_id, status);
                CREATE INDEX IF NOT EXISTS idx_events_event_created_at ON events(event, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_client_id ON events(client_id);
                CREATE INDEX IF NOT EXISTS idx_outbound_scheduled_sent ON outbound(scheduled_at, sent_at);
                CREATE INDEX IF NOT EXISTS idx_outbound_client_kind ON outbound(client_id, kind);
                CREATE INDEX IF NOT EXISTS idx_catalog_items_active_sort ON catalog_items(is_active, status, sort_order, name COLLATE NOCASE);
                """
            )
            _ensure_column(conn, "clients", "opted_out_at", "TEXT")
            _ensure_column(conn, "clients", "bot_paused_at", "TEXT")
            _ensure_column(conn, "clients", "paused_by", "TEXT")
            _ensure_column(conn, "daily_stock", "price", "INTEGER")
            _ensure_column(conn, "daily_stock", "unit", "TEXT")
            self._migrate_latest_daily_stock_to_catalog(conn)

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
                "SELECT id, telegram_id, username, stage, summary, opted_out_at, bot_paused_at, paused_by FROM clients WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
        return self._client_from_row(row) if row else None

    def get_client_by_id(self, client_id: int) -> ClientRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, telegram_id, username, stage, summary, opted_out_at, bot_paused_at, paused_by FROM clients WHERE id = ?",
                (client_id,),
            ).fetchone()
        return self._client_from_row(row) if row else None

    def update_client_state(self, *, client_id: int, stage: str, summary: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE clients SET stage = ?, summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (stage, summary, client_id),
            )

    def mark_client_opted_out(self, *, client_id: int, opted_out_at: datetime | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE clients SET opted_out_at = COALESCE(opted_out_at, ?), updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (_format_dt(opted_out_at), client_id),
            )

    def pause_client(self, *, client_id: int, paused_by: str, reason: str, paused_at: datetime | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE clients SET bot_paused_at = COALESCE(bot_paused_at, ?), paused_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (_format_dt(paused_at), paused_by, client_id),
            )
        self.record_event(client_id=client_id, order_id=None, event=EventName.BOT_PAUSED, payload={"reason": reason}, created_at=paused_at)

    def resume_client(self, *, client_id: int, reason: str, resumed_at: datetime | None = None) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE clients SET bot_paused_at = NULL, paused_by = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (client_id,))
        self.record_event(client_id=client_id, order_id=None, event=EventName.BOT_RESUMED, payload={"reason": reason}, created_at=resumed_at)

    def list_paused_clients(self) -> list[ClientRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, telegram_id, username, stage, summary, opted_out_at, bot_paused_at, paused_by FROM clients WHERE bot_paused_at IS NOT NULL ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [self._client_from_row(row) for row in rows]

    @staticmethod
    def _dialogue_filters(
        *,
        filter_name: str | None,
        active_days: int | None,
        q: str | None,
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []
        if filter_name == "paused":
            clauses.append("c.bot_paused_at IS NOT NULL")
        elif filter_name == "ready":
            clauses.append("o.card_json LIKE '%\"admin_request_sent\": true%'")
        if active_days is not None:
            clauses.append("datetime(lm.last_message_at) >= datetime('now', ?)")
            params.append(f"-{active_days} days")
        query = (q or "").strip()
        if query:
            like = f"%{query.lower().replace(chr(1105), chr(1077))}%"
            digits = _digits_only(query)
            search_clauses = [
                ("pylower(COALESCE(c.username, '')) LIKE ?", [like]),
                ("CAST(c.telegram_id AS TEXT) LIKE ?", [f"%{digits or query}%"]),
                ("CAST(c.id AS TEXT) = ?", [query]),
                (
                    "EXISTS (SELECT 1 FROM orders so WHERE so.client_id = c.id AND ("
                    " pylower(COALESCE(json_extract(so.card_json, '$.sender_name'), '')) LIKE ?"
                    " OR pylower(COALESCE(json_extract(so.card_json, '$.recipient_name'), '')) LIKE ?"
                    " OR pylower(COALESCE(json_extract(so.card_json, '$.address'), '')) LIKE ?"
                    "))",
                    [like, like, like],
                ),
            ]
            if len(digits) >= 4:
                phone_pattern = f"%{digits}%"
                search_clauses.append(
                    (
                        "EXISTS (SELECT 1 FROM orders so WHERE so.client_id = c.id AND ("
                        f" {_PHONE_DIGITS_SQL.format(field='sender_phone')} LIKE ?"
                        f" OR {_PHONE_DIGITS_SQL.format(field='recipient_phone')} LIKE ?"
                        "))",
                        [phone_pattern, phone_pattern],
                    )
                )
            clauses.append("(" + " OR ".join(clause for clause, _ in search_clauses) + ")")
            for _, clause_params in search_clauses:
                params.extend(clause_params)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        return where, params

    def count_dialogues(
        self,
        *,
        filter_name: str | None = None,
        active_days: int | None = None,
        q: str | None = None,
    ) -> int:
        where, params = self._dialogue_filters(filter_name=filter_name, active_days=active_days, q=q)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM clients c
                LEFT JOIN orders o ON o.client_id = c.id AND o.status IN ('draft', 'submitted', 'confirmed', 'in_production', 'ready', 'active')
                LEFT JOIN (
                    SELECT m1.client_id, m1.created_at AS last_message_at, m1.text AS last_message_text
                    FROM messages m1
                    JOIN (SELECT client_id, MAX(id) AS max_id FROM messages GROUP BY client_id) latest ON latest.max_id = m1.id
                ) lm ON lm.client_id = c.id
                {where}
                """,
                params,
            ).fetchone()
        return int(row["total"]) if row else 0

    def list_dialogues(
        self,
        *,
        filter_name: str | None = None,
        active_days: int | None = None,
        limit: int = 200,
        offset: int = 0,
        q: str | None = None,
    ) -> list[DialogueRecord]:
        where, params = self._dialogue_filters(filter_name=filter_name, active_days=active_days, q=q)
        params = [*params, limit, max(0, offset)]
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    c.id AS client_id, c.telegram_id, c.username, c.stage, c.summary,
                    c.opted_out_at, c.bot_paused_at, c.paused_by,
                    o.id AS order_id, o.status AS order_status, o.card_json, o.created_at AS order_created_at, o.updated_at AS order_updated_at,
                    lm.last_message_at, lm.last_message_text
                FROM clients c
                LEFT JOIN orders o ON o.client_id = c.id AND o.status IN ('draft', 'submitted', 'confirmed', 'in_production', 'ready', 'active')
                LEFT JOIN (
                    SELECT m1.client_id, m1.created_at AS last_message_at, m1.text AS last_message_text
                    FROM messages m1
                    JOIN (SELECT client_id, MAX(id) AS max_id FROM messages GROUP BY client_id) latest ON latest.max_id = m1.id
                ) lm ON lm.client_id = c.id
                {where}
                ORDER BY datetime(COALESCE(lm.last_message_at, '1970-01-01')) DESC, c.id DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._dialogue_from_row(row) for row in rows]

    def count_messages(self, *, client_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM messages WHERE client_id = ?", (client_id,)).fetchone()
        return int(row["total"]) if row else 0

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
                INSERT INTO daily_stock (stock_date, item_name, status, quantity_text, quantity_number, price, unit, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        stock_date.isoformat(),
                        item.name,
                        item.status.value,
                        item.quantity_text,
                        item.quantity_number,
                        item.price,
                        item.unit,
                        updated_by,
                    )
                    for item in items
                ],
            )

    def list_daily_stock(self, *, stock_date: date) -> list[StockItem]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT item_name, status, quantity_text, quantity_number, price, unit
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
                price=row["price"],
                unit=row["unit"],
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

    def upsert_catalog_item(
        self,
        *,
        name: str,
        quantity_number: int | None = None,
        quantity_text: str | None = None,
        price: int | None = None,
        unit: str | None = None,
        status: StockStatus | str | None = None,
        is_active: bool = True,
        sort_order: int = 0,
        updated_by: int | None = None,
        journal_date: date | None = None,
    ) -> CatalogItemRecord:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("catalog item name is required")
        quantity_text = (quantity_text or ("нет" if quantity_number == 0 else str(quantity_number) if quantity_number is not None else "есть")).strip()
        computed_status = StockStatus(status) if status is not None else _catalog_status_from_quantity(quantity_text, quantity_number)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO catalog_items (name, name_key, status, quantity_number, quantity_text, price, unit, is_active, sort_order, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name_key) DO UPDATE SET
                    name = excluded.name,
                    status = excluded.status,
                    quantity_number = excluded.quantity_number,
                    quantity_text = excluded.quantity_text,
                    price = excluded.price,
                    unit = excluded.unit,
                    is_active = excluded.is_active,
                    sort_order = excluded.sort_order,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (clean_name, _catalog_name_key(clean_name), computed_status.value, quantity_number, quantity_text, price, unit or "шт", int(is_active), sort_order, updated_by),
            )
        item = self.get_catalog_item_by_name(clean_name)
        if item is None:
            raise RuntimeError("catalog item upsert failed")
        self._append_catalog_daily_stock(item, updated_by=updated_by or 0, stock_date=journal_date)
        return item

    def update_catalog_item(self, item_id: int, **changes) -> CatalogItemRecord:
        existing = self.get_catalog_item(item_id)
        if existing is None:
            raise KeyError(f"catalog item {item_id} not found")
        updated_by = changes.pop("updated_by", existing.updated_by)
        name = str(changes.get("name", existing.name)).strip()
        if not name:
            raise ValueError("catalog item name is required")
        quantity_number = changes.get("quantity_number", existing.quantity_number)
        quantity_text = changes.get("quantity_text")
        if quantity_text is None:
            quantity_text = "нет" if quantity_number == 0 else str(quantity_number) if quantity_number is not None else existing.quantity_text
        price = changes.get("price", existing.price)
        unit = changes.get("unit", existing.unit) or "шт"
        status = StockStatus(changes["status"]) if "status" in changes and changes["status"] is not None else _catalog_status_from_quantity(str(quantity_text), quantity_number)
        is_active = bool(changes.get("is_active", existing.is_active))
        sort_order = int(changes.get("sort_order", existing.sort_order))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE catalog_items
                SET name = ?, name_key = ?, status = ?, quantity_number = ?, quantity_text = ?, price = ?, unit = ?, is_active = ?, sort_order = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (name, _catalog_name_key(name), status.value, quantity_number, str(quantity_text), price, unit, int(is_active), sort_order, updated_by, item_id),
            )
        updated = self.get_catalog_item(item_id)
        if updated is None:
            raise RuntimeError("catalog item update failed")
        self._append_catalog_daily_stock(updated, updated_by=updated_by or 0)
        return updated

    def get_catalog_item(self, item_id: int) -> CatalogItemRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, status, quantity_text, quantity_number, price, unit, is_active, sort_order, updated_by, updated_at, created_at FROM catalog_items WHERE id = ?",
                (item_id,),
            ).fetchone()
        return self._catalog_item_from_row(row) if row else None

    def get_catalog_item_by_name(self, name: str) -> CatalogItemRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, status, quantity_text, quantity_number, price, unit, is_active, sort_order, updated_by, updated_at, created_at FROM catalog_items WHERE name_key = ?",
                (_catalog_name_key(name),),
            ).fetchone()
        return self._catalog_item_from_row(row) if row else None

    def list_catalog_items(self, *, include_inactive: bool = False, q: str = "") -> list[CatalogItemRecord]:
        clauses = [] if include_inactive else ["is_active = 1"]
        params: list[object] = []
        if q.strip():
            clauses.append("name LIKE ? COLLATE NOCASE")
            params.append(f"%{q.strip()}%")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, name, status, quantity_text, quantity_number, price, unit, is_active, sort_order, updated_by, updated_at, created_at
                FROM catalog_items
                {where}
                ORDER BY CASE status WHEN 'unavailable' THEN 0 WHEN 'low' THEN 1 ELSE 2 END, sort_order ASC, name COLLATE NOCASE ASC
                """,
                params,
            ).fetchall()
        return [self._catalog_item_from_row(row) for row in rows]

    def _append_catalog_daily_stock(self, item: CatalogItemRecord, *, updated_by: int, stock_date: date | None = None) -> None:
        today = (stock_date or datetime.now(timezone.utc).date()).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_stock (stock_date, item_name, status, quantity_text, quantity_number, price, unit, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (today, item.name, item.status.value, item.quantity_text, item.quantity_number, item.price, item.unit, updated_by),
            )

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
                    c.summary AS client_summary,
                    c.opted_out_at AS client_opted_out_at,
                    c.bot_paused_at AS client_bot_paused_at,
                    c.paused_by AS client_paused_by
                FROM orders o
                JOIN clients c ON c.id = o.client_id
                WHERE o.status IN ('draft', 'submitted', 'confirmed', 'in_production', 'ready', 'active')
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
                    opted_out_at=row["client_opted_out_at"],
                    bot_paused_at=row["client_bot_paused_at"],
                    paused_by=row["client_paused_by"],
                ),
            )
            for row in rows
        ]

    def record_event(
        self,
        *,
        client_id: int,
        order_id: int | None,
        event: EventName | str,
        payload: dict | None = None,
        created_at: datetime | None = None,
    ) -> None:
        event_value = event.value if isinstance(event, EventName) else str(event)
        payload_json = json.dumps(sanitize_payload(payload), ensure_ascii=False)
        default_created_at = datetime.now(timezone.utc).replace(tzinfo=None)
        created_at_text = (created_at or default_created_at).strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO events (client_id, order_id, event, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (client_id, order_id, event_value, payload_json, created_at_text),
            )

    def list_events(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        client_id: int | None = None,
        event: EventName | str | None = None,
    ) -> list[EventRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if date_from is not None:
            clauses.append("date(created_at) >= date(?)")
            params.append(date_from.isoformat())
        if date_to is not None:
            clauses.append("date(created_at) <= date(?)")
            params.append(date_to.isoformat())
        if client_id is not None:
            clauses.append("client_id = ?")
            params.append(client_id)
        if event is not None:
            clauses.append("event = ?")
            params.append(event.value if isinstance(event, EventName) else str(event))
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, client_id, order_id, event, payload_json, created_at
                FROM events
                {where}
                ORDER BY id ASC
                """,
                params,
            ).fetchall()
        return [
            EventRecord(
                id=int(row["id"]),
                client_id=int(row["client_id"]),
                order_id=int(row["order_id"]) if row["order_id"] is not None else None,
                event=row["event"],
                payload_json=row["payload_json"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def schedule_outbound(self, *, client_id: int, order_id: int | None, kind, scheduled_at: datetime) -> OutboundRecord:
        kind_value = kind.value if hasattr(kind, "value") else str(kind)
        scheduled_at_text = _format_dt(scheduled_at)
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT id, client_id, order_id, kind, scheduled_at, sent_at, cancelled_at, attempt_count, created_at
                FROM outbound
                WHERE client_id = ? AND kind = ? AND sent_at IS NULL AND cancelled_at IS NULL
                ORDER BY id DESC
                LIMIT 1
                """,
                (client_id, kind_value),
            ).fetchone()
            if existing:
                return self._outbound_from_row(existing)
            cursor = conn.execute(
                "INSERT INTO outbound (client_id, order_id, kind, scheduled_at) VALUES (?, ?, ?, ?)",
                (client_id, order_id, kind_value, scheduled_at_text),
            )
            row = conn.execute(
                "SELECT id, client_id, order_id, kind, scheduled_at, sent_at, cancelled_at, attempt_count, created_at FROM outbound WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        return self._outbound_from_row(row)

    def get_outbound(self, outbound_id: int) -> OutboundRecord:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, client_id, order_id, kind, scheduled_at, sent_at, cancelled_at, attempt_count, created_at FROM outbound WHERE id = ?",
                (outbound_id,),
            ).fetchone()
        if row is None:
            raise KeyError(outbound_id)
        return self._outbound_from_row(row)

    def list_due_outbound(self, *, now: datetime) -> list[OutboundRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, client_id, order_id, kind, scheduled_at, sent_at, cancelled_at, attempt_count, created_at
                FROM outbound
                WHERE datetime(scheduled_at) <= datetime(?) AND sent_at IS NULL AND cancelled_at IS NULL
                ORDER BY datetime(scheduled_at), id
                """,
                (_format_dt(now),),
            ).fetchall()
        return [self._outbound_from_row(row) for row in rows]

    def has_outbound(self, *, client_id: int | None = None, order_id: int | None = None, kind=None) -> bool:
        clauses: list[str] = []
        params: list[object] = []
        if client_id is not None:
            clauses.append("client_id = ?")
            params.append(client_id)
        if order_id is not None:
            clauses.append("order_id = ?")
            params.append(order_id)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind.value if hasattr(kind, "value") else str(kind))
        where = " AND ".join(clauses) or "1=1"
        with self._connect() as conn:
            row = conn.execute(f"SELECT 1 FROM outbound WHERE {where} LIMIT 1", params).fetchone()
        return row is not None

    def mark_outbound_sent(self, outbound_id: int, *, sent_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE outbound SET sent_at = ? WHERE id = ?", (_format_dt(sent_at), outbound_id))

    def reschedule_outbound(self, outbound_id: int, *, scheduled_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE outbound SET scheduled_at = ? WHERE id = ?", (_format_dt(scheduled_at), outbound_id))

    def increment_outbound_attempt(self, outbound_id: int, *, now: datetime, cancel_after_attempts: int = 3) -> OutboundRecord:
        with self._connect() as conn:
            conn.execute("UPDATE outbound SET attempt_count = attempt_count + 1 WHERE id = ?", (outbound_id,))
            row = conn.execute(
                "SELECT id, client_id, order_id, kind, scheduled_at, sent_at, cancelled_at, attempt_count, created_at FROM outbound WHERE id = ?",
                (outbound_id,),
            ).fetchone()
            if row and int(row["attempt_count"]) >= cancel_after_attempts:
                conn.execute("UPDATE outbound SET cancelled_at = ? WHERE id = ?", (_format_dt(now), outbound_id))
                row = conn.execute(
                    "SELECT id, client_id, order_id, kind, scheduled_at, sent_at, cancelled_at, attempt_count, created_at FROM outbound WHERE id = ?",
                    (outbound_id,),
                ).fetchone()
        return self._outbound_from_row(row)

    def cancel_pending_followups(self, *, client_id: int, cancelled_at: datetime | None = None) -> list[OutboundRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, client_id, order_id, kind, scheduled_at, sent_at, cancelled_at, attempt_count, created_at
                FROM outbound
                WHERE client_id = ? AND kind IN ('followup_1', 'followup_2') AND sent_at IS NULL AND cancelled_at IS NULL
                """,
                (client_id,),
            ).fetchall()
            conn.execute(
                """
                UPDATE outbound SET cancelled_at = ?
                WHERE client_id = ? AND kind IN ('followup_1', 'followup_2') AND sent_at IS NULL AND cancelled_at IS NULL
                """,
                (_format_dt(cancelled_at), client_id),
            )
        return [self._outbound_from_row(row) for row in rows]

    def get_active_order(self, *, client_id: int) -> OrderRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, client_id, status, card_json, created_at, updated_at
                FROM orders
                WHERE client_id = ? AND status IN ('draft', 'submitted', 'confirmed', 'in_production', 'ready', 'active')
                ORDER BY id DESC
                LIMIT 1
                """,
                (client_id,),
            ).fetchone()
        return self._order_from_row(row) if row else None

    def list_orders_for_client(self, *, client_id: int, limit: int = 20) -> list[OrderRecord]:
        """Все заказы клиента, новые первыми.

        Панель показывала только активный, поэтому после старта нового заказа
        смена статуса выглядела так, будто карточку очистили, а статус не сохранился.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, client_id, status, card_json, created_at, updated_at
                FROM orders
                WHERE client_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (client_id, limit),
            ).fetchall()
        return [self._order_from_row(row) for row in rows]

    def get_order_by_id(self, order_id: int) -> OrderRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, client_id, status, card_json, created_at, updated_at FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
        return self._order_from_row(row) if row else None

    def get_or_create_active_order(self, *, client_id: int) -> OrderRecord:
        existing = self.get_active_order(client_id=client_id)
        if existing:
            return existing
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO orders (client_id, status, card_json) VALUES (?, 'draft', ?)",
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

    def update_order_status(
        self,
        *,
        order_id: int,
        status: str,
        changed_by: str,
        changed_at: datetime | None = None,
    ) -> OrderRecord:
        if status not in ORDER_STATUSES and status not in {"superseded", "completed"}:
            raise ValueError(f"invalid order status: {status}")
        order = self.get_order_by_id(order_id)
        if order is None:
            raise KeyError(order_id)
        if order.status == status:
            return order
        changed_at = changed_at or datetime.now(timezone.utc).replace(tzinfo=None)
        changed_at_text = _format_dt(changed_at)
        with self._connect() as conn:
            conn.execute("UPDATE orders SET status = ?, updated_at = ? WHERE id = ?", (status, changed_at_text, order_id))
        updated = self.get_order_by_id(order_id)
        self.record_event(
            client_id=order.client_id,
            order_id=order.id,
            event=EventName.ORDER_STATUS_CHANGED,
            payload={"old_status": order.status, "new_status": status, "changed_by": changed_by},
            created_at=changed_at,
        )
        if status == "confirmed":
            self.schedule_outbound(client_id=order.client_id, order_id=order.id, kind="order_confirmed", scheduled_at=changed_at)
        elif status == "ready":
            self.schedule_outbound(client_id=order.client_id, order_id=order.id, kind="order_ready", scheduled_at=changed_at)
        return updated

    def count_orders_by_status(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS count FROM orders GROUP BY status").fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    def close_active_orders(self, *, client_id: int, status: str = "superseded") -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE client_id = ? AND status IN ('draft', 'submitted', 'confirmed', 'in_production', 'ready', 'active')",
                (status, client_id),
            )

    def cleanup_pii_older_than(
        self,
        *,
        retention_days: int,
        event_retention_days: int = 90,
        now: datetime | None = None,
    ) -> RetentionCleanupResult:
        """Delete old message history and anonymize PII in old completed orders."""
        if retention_days < 1:
            raise ValueError("retention_days must be >= 1")
        if event_retention_days < 1:
            raise ValueError("event_retention_days must be >= 1")
        reference_time = now or datetime.now(timezone.utc)
        if reference_time.tzinfo is not None:
            reference_time = reference_time.astimezone(timezone.utc).replace(tzinfo=None)
        cutoff_text = (reference_time - timedelta(days=retention_days)).strftime("%Y-%m-%d %H:%M:%S")
        event_cutoff_text = (reference_time - timedelta(days=event_retention_days)).strftime("%Y-%m-%d %H:%M:%S")

        with self._connect() as conn:
            deleted_messages = conn.execute("DELETE FROM messages WHERE datetime(created_at) < datetime(?)", (cutoff_text,)).rowcount
            deleted_events = conn.execute("DELETE FROM events WHERE datetime(created_at) < datetime(?)", (event_cutoff_text,)).rowcount
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
            deleted_events=max(deleted_events, 0),
        )

    def delete_client_data_by_telegram_id(self, telegram_id: int) -> bool:
        """Delete one client's messages and orders for manual data-erasure requests."""
        client = self.get_client_by_telegram_id(telegram_id)
        if client is None:
            return False
        with self._connect() as conn:
            conn.execute("DELETE FROM events WHERE client_id = ?", (client.id,))
            conn.execute("DELETE FROM messages WHERE client_id = ?", (client.id,))
            conn.execute("DELETE FROM orders WHERE client_id = ?", (client.id,))
            conn.execute("DELETE FROM clients WHERE id = ?", (client.id,))
        return True

    def _migrate_latest_daily_stock_to_catalog(self, conn: sqlite3.Connection) -> None:
        existing = conn.execute("SELECT 1 FROM catalog_items LIMIT 1").fetchone()
        if existing is not None:
            return
        row = conn.execute("SELECT MAX(stock_date) AS stock_date FROM daily_stock").fetchone()
        if row is None or row["stock_date"] is None:
            return
        rows = conn.execute(
            """
            SELECT item_name, status, quantity_text, quantity_number, price, unit, updated_by
            FROM daily_stock
            WHERE stock_date = ?
            ORDER BY id ASC
            """,
            (row["stock_date"],),
        ).fetchall()
        for sort_order, stock_row in enumerate(rows):
            name = stock_row["item_name"]
            conn.execute(
                """
                INSERT OR IGNORE INTO catalog_items (name, name_key, status, quantity_number, quantity_text, price, unit, is_active, sort_order, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    name,
                    _catalog_name_key(name),
                    stock_row["status"],
                    stock_row["quantity_number"],
                    stock_row["quantity_text"],
                    stock_row["price"],
                    stock_row["unit"],
                    sort_order,
                    stock_row["updated_by"],
                ),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        # SQLite lower() folds ASCII only, so search by Russian names needs Python casefolding.
        conn.create_function("pylower", 1, _pylower)
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
            opted_out_at=row["opted_out_at"] if "opted_out_at" in row.keys() else None,
            bot_paused_at=row["bot_paused_at"] if "bot_paused_at" in row.keys() else None,
            paused_by=row["paused_by"] if "paused_by" in row.keys() else None,
        )

    @staticmethod
    def _catalog_item_from_row(row: sqlite3.Row) -> CatalogItemRecord:
        return CatalogItemRecord(
            id=int(row["id"]),
            name=row["name"],
            status=StockStatus(row["status"]),
            quantity_text=row["quantity_text"],
            quantity_number=row["quantity_number"],
            price=row["price"],
            unit=row["unit"],
            is_active=bool(row["is_active"]),
            sort_order=int(row["sort_order"]),
            updated_by=row["updated_by"],
            updated_at=row["updated_at"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _dialogue_from_row(row: sqlite3.Row) -> DialogueRecord:
        client = ClientRecord(
            id=int(row["client_id"]),
            telegram_id=int(row["telegram_id"]),
            username=row["username"],
            stage=row["stage"],
            summary=row["summary"],
            opted_out_at=row["opted_out_at"],
            bot_paused_at=row["bot_paused_at"],
            paused_by=row["paused_by"],
        )
        order = None
        if row["order_id"] is not None:
            order = OrderRecord(
                id=int(row["order_id"]),
                client_id=client.id,
                status=row["order_status"],
                card=OrderCard.from_dict(json.loads(row["card_json"] or "{}")),
                created_at=row["order_created_at"],
                updated_at=row["order_updated_at"],
            )
        return DialogueRecord(client=client, active_order=order, last_message_at=row["last_message_at"], last_message_text=row["last_message_text"])

    @staticmethod
    def _outbound_from_row(row: sqlite3.Row) -> OutboundRecord:
        return OutboundRecord(
            id=int(row["id"]),
            client_id=int(row["client_id"]),
            order_id=int(row["order_id"]) if row["order_id"] is not None else None,
            kind=row["kind"],
            scheduled_at=row["scheduled_at"],
            sent_at=row["sent_at"],
            cancelled_at=row["cancelled_at"],
            attempt_count=int(row["attempt_count"]),
            created_at=row["created_at"],
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
        sheet_row_written=card.sheet_row_written,
    )


def _catalog_name_key(name: str) -> str:
    return " ".join(name.strip().lower().replace("ё", "е").split())


def _catalog_status_from_quantity(quantity_text: str, quantity_number: int | None) -> StockStatus:
    text = quantity_text.lower().replace("ё", "е")
    if quantity_number == 0 or any(word in text for word in ("нет", "законч", "отсутств")):
        return StockStatus.UNAVAILABLE
    if any(word in text for word in ("мало", "чуть", "немного")):
        return StockStatus.LOW
    return StockStatus.AVAILABLE


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _format_dt(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc).replace(tzinfo=None)
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return current.strftime("%Y-%m-%d %H:%M:%S")
