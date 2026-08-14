from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.telegram_runtime import update_active_order_from_messages


def test_update_active_order_from_messages_merges_with_existing_order(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username=None)

    card = update_active_order_from_messages(
        repo,
        client_id=client.id,
        recent_messages=["Менеджер: С каким бюджетом сориентировать вас по букету?", "Клиент: 5000", "Клиент: Самовывоз"],
    )
    card = update_active_order_from_messages(
        repo,
        client_id=client.id,
        recent_messages=["Клиент: Сегодня в 18:00", "Клиент: Даниил 89990000006"],
    )

    assert card.budget == 5000
    assert card.fulfillment_type == "pickup"
    assert card.delivery_time == "18:00"
    assert card.sender_name == "Даниил"
