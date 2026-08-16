from datetime import datetime, timedelta, timezone

from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard


def test_settings_expose_configurable_pii_retention_window():
    settings = Settings(pii_retention_days=14)

    assert settings.pii_retention_days == 14


def test_cleanup_pii_uses_configurable_event_retention_window(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client_user")
    repo.record_event(client_id=client.id, order_id=None, event="message_received")
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=61)).strftime("%Y-%m-%d %H:%M:%S")
    with repo._connect() as conn:
        conn.execute("UPDATE events SET created_at = ? WHERE client_id = ?", (old_timestamp, client.id))

    keep = repo.cleanup_pii_older_than(retention_days=30, event_retention_days=90, now=datetime.now(timezone.utc))
    delete = repo.cleanup_pii_older_than(retention_days=30, event_retention_days=60, now=datetime.now(timezone.utc))

    assert keep.deleted_events == 0
    assert delete.deleted_events == 1


def test_cleanup_pii_deletes_messages_older_than_retention_window(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client_user")
    old_message = repo.add_message(client_id=client.id, direction="in", text="Адрес Ленина 1, телефон 89990000001")
    repo.add_message(client_id=client.id, direction="in", text="свежее сообщение")
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%d %H:%M:%S")
    with repo._connect() as conn:
        conn.execute("UPDATE messages SET created_at = ? WHERE id = ?", (old_timestamp, old_message.id))

    result = repo.cleanup_pii_older_than(retention_days=30, now=datetime.now(timezone.utc))

    messages = repo.list_messages(client_id=client.id, limit=10)
    assert result.deleted_messages == 1
    assert [message.text for message in messages] == ["свежее сообщение"]


def test_cleanup_pii_anonymizes_old_completed_order_but_keeps_recent_active_order(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    old_client = repo.upsert_client(telegram_id=123, username="old_client")
    active_client = repo.upsert_client(telegram_id=456, username="active_client")

    old_order = repo.get_or_create_active_order(client_id=old_client.id)
    repo.update_order_card(
        order_id=old_order.id,
        card=OrderCard(
            budget=5000,
            colors=["белый"],
            fulfillment_type="delivery",
            delivery_date="today",
            delivery_time="18:00",
            address="ул. Ленина 1, кв 2",
            sender_name="Даниил",
            sender_phone="89990000001",
            recipient_name="Анна",
            recipient_phone="89990000002",
            payment_method="transfer",
            postcard_text="От Дани",
            custom_fields={"patient_name": "Анна"},
            admin_request_sent=True,
            client_summary_sent=True,
        ),
    )
    repo.close_active_orders(client_id=old_client.id, status="completed")

    active_order = repo.get_or_create_active_order(client_id=active_client.id)
    repo.update_order_card(
        order_id=active_order.id,
        card=OrderCard(
            budget=7000,
            colors=["красный"],
            fulfillment_type="delivery",
            delivery_date="tomorrow",
            delivery_time="19:00",
            address="ул. Пушкина 10",
            sender_name="Мария",
            sender_phone="89990000003",
            recipient_name="Ольга",
            recipient_phone="89990000004",
            payment_method="cash",
        ),
    )

    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%d %H:%M:%S")
    with repo._connect() as conn:
        conn.execute("UPDATE orders SET updated_at = ? WHERE id = ?", (old_timestamp, old_order.id))

    result = repo.cleanup_pii_older_than(retention_days=30, now=datetime.now(timezone.utc))

    with repo._connect() as conn:
        old_row = conn.execute("SELECT card_json FROM orders WHERE id = ?", (old_order.id,)).fetchone()
    anonymized = OrderCard.from_dict(__import__("json").loads(old_row["card_json"]))
    active = repo.get_active_order(client_id=active_client.id).card

    assert result.anonymized_orders == 1
    assert anonymized.address is None
    assert anonymized.sender_name is None
    assert anonymized.sender_phone is None
    assert anonymized.recipient_name is None
    assert anonymized.recipient_phone is None
    assert anonymized.postcard_text is None
    assert anonymized.custom_fields == {}
    assert anonymized.budget == 5000
    assert active.address == "ул. Пушкина 10"
    assert active.sender_phone == "89990000003"


def test_delete_client_data_by_telegram_id_removes_client_messages_and_orders(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client_user")
    repo.add_message(client_id=client.id, direction="in", text="телефон 89990000001")
    repo.get_or_create_active_order(client_id=client.id)

    deleted = repo.delete_client_data_by_telegram_id(123)

    assert deleted is True
    assert repo.get_client_by_telegram_id(123) is None
    assert repo.delete_client_data_by_telegram_id(123) is False
