from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard
from amelia_manager.telegram_runtime import should_start_new_order, update_active_order_from_messages


RICH_NEW_ORDER = "Добрый вечер! Нужен букет на 12 августа самовывоз в 12:00\nБукет до 10000 рублей, по цветам нежно белый, кремовый"


def test_should_start_new_order_when_previous_order_was_already_sent_to_admin():
    old_card = OrderCard(
        budget=5000,
        colors=["синий", "белый", "розовый", "желтый"],
        fulfillment_type="pickup",
        delivery_date="today",
        delivery_time="18:00",
        sender_name="Даниил",
        sender_phone="89990000005",
        payment_method="cash",
        admin_request_sent=True,
    )

    assert should_start_new_order(RICH_NEW_ORDER, old_card) is True


def test_rich_new_order_does_not_merge_old_ready_card(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username=None)
    old_order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(
        order_id=old_order.id,
        card=OrderCard(
            budget=5000,
            colors=["синий", "белый", "розовый", "желтый"],
            fulfillment_type="pickup",
            delivery_date="today",
            delivery_time="18:00",
            sender_name="Даниил",
            sender_phone="89990000005",
            payment_method="cash",
            admin_request_sent=True,
        ),
    )

    card = update_active_order_from_messages(repo, client_id=client.id, recent_messages=[f"Клиент: {RICH_NEW_ORDER}"])
    active = repo.get_active_order(client_id=client.id)

    assert active.id != old_order.id
    assert card.budget == 10000
    assert card.delivery_date == "12 августа"
    assert card.delivery_time == "12:00"
    assert card.fulfillment_type == "pickup"
    assert card.colors == ["белый", "кремовый", "нежный стиль"]
    assert card.sender_name is None
    assert card.sender_phone is None
    assert card.payment_method is None
    assert card.admin_request_sent is False
