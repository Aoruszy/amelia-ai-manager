from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.telegram_runtime import build_admin_order_request_if_needed, update_active_order_from_messages


def test_ready_pickup_after_cash_and_time_builds_admin_request(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")

    card = update_active_order_from_messages(
        repo,
        client_id=client.id,
        recent_messages=[
            "Клиент: Бюджет 5000, выбираю девушке",
            "Клиент: розовый желтый белый",
            "Клиент: Самовывоз",
            "Клиент: Оплачу на месте",
            "Клиент: Даниил 89990000005",
            "Менеджер: Подскажите, к какому примерно времени сегодня планируете забрать букет?",
            "Клиент: 18:00",
        ],
    )
    order = repo.get_active_order(client_id=client.id)
    request = build_admin_order_request_if_needed(repo, order=order, client_label="@client / 123")

    assert card.is_ready_for_admin_request() is True
    assert request is not None
    assert "Новая заявка Amelia Flowers" in request
    assert "самовывоз" in request.lower()
