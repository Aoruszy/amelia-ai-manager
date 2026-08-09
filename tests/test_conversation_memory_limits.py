from datetime import datetime, timedelta

from amelia_manager.db.repository import SQLiteRepository


def test_list_messages_can_filter_latest_messages_by_age_window(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client_user")

    old = repo.add_message(client_id=client.id, direction="in", text="старое сообщение")
    with repo._connect() as conn:
        conn.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            ((datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"), old.id),
        )

    for index in range(1, 13):
        repo.add_message(client_id=client.id, direction="in", text=f"свежее {index}")

    messages = repo.list_messages(client_id=client.id, limit=10, since_days=7)

    assert [message.text for message in messages] == [f"свежее {index}" for index in range(3, 13)]
    assert "старое сообщение" not in [message.text for message in messages]


def test_list_messages_without_age_filter_keeps_existing_behavior(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client_user")

    old = repo.add_message(client_id=client.id, direction="in", text="старое сообщение")
    with repo._connect() as conn:
        conn.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            ((datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"), old.id),
        )
    repo.add_message(client_id=client.id, direction="in", text="свежее сообщение")

    messages = repo.list_messages(client_id=client.id, limit=10)

    assert [message.text for message in messages] == ["старое сообщение", "свежее сообщение"]
