from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard
from amelia_manager.telegram_runtime import should_start_new_order, update_active_order_from_messages


def _old_pickup_card() -> OrderCard:
    return OrderCard(
        budget=15000,
        colors=["красный"],
        fulfillment_type="pickup",
        delivery_date="tomorrow",
        delivery_time="23:00",
        sender_name="Даниил",
        sender_phone="89990000005",
        payment_method="cash",
    )


def test_greeting_plus_delivery_address_starts_new_order_not_old_continuation():
    assert should_start_new_order("Здравствуйте нужна доставка на гайдара 173", _old_pickup_card()) is True


def test_runtime_greeting_delivery_address_resets_stale_order(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")
    old_order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(order_id=old_order.id, card=_old_pickup_card())

    card = update_active_order_from_messages(
        repo,
        client_id=client.id,
        recent_messages=["Клиент: Здравствуйте нужна доставка на гайдара 173"],
    )
    active = repo.get_active_order(client_id=client.id)

    assert active.id != old_order.id
    assert card.fulfillment_type == "delivery"
    assert card.address == "гайдара 173"
    assert card.budget is None
    assert card.colors == []
    assert card.delivery_time is None
    assert card.sender_name is None
    assert card.payment_method is None
    assert card.is_ready_for_admin_request() is False


def test_runtime_greeting_then_delivery_address_resets_stale_order(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")
    old_order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(order_id=old_order.id, card=_old_pickup_card())

    card = update_active_order_from_messages(
        repo,
        client_id=client.id,
        recent_messages=[
            "Клиент: Здравствуйте",
            "Менеджер: Здравствуйте 🙂 Чем могу помочь?",
            "Клиент: Нужна доставка на Гайдара 173",
        ],
    )
    active = repo.get_active_order(client_id=client.id)

    assert active.id != old_order.id
    assert card.fulfillment_type == "delivery"
    assert card.address == "Гайдара 173"
    assert card.budget is None
    assert card.colors == []
    assert card.delivery_time is None
    assert card.payment_method is None
