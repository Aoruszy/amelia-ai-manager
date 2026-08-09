from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.telegram_runtime import update_active_order_from_messages


OLD_AND_NEW_HISTORY = [
    "Клиент: Нужны цветы",
    "Клиент: Бюджет 5000, выбираю девушке",
    "Клиент: Розовый желтый белый",
    "Клиент: Самовывоз",
    "Клиент: Оплачу на месте",
    "Клиент: Даниил 89990000005",
    "Клиент: 18:00",
    "Менеджер: Итог заказа: старый заказ",
    "Клиент: Добрый вечер! Нужен букет на 12 августа самовывоз в 12:00\nБукет до 10000 рублей, по цветам нежно белый, кремовый",
    "Клиент: Иван 89990000010",
]


def test_new_active_order_extracts_only_from_latest_order_start_when_no_active_card(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username=None)

    card = update_active_order_from_messages(repo, client_id=client.id, recent_messages=OLD_AND_NEW_HISTORY)

    assert card.budget == 10000
    assert card.delivery_date == "2026-08-12"
    assert card.delivery_time == "12:00"
    assert card.colors == ["белый", "кремовый", "нежный стиль"]
    assert card.sender_name == "Иван"
    assert card.sender_phone == "89990000010"
    assert "розовый" not in card.colors
    assert card.payment_method is None
