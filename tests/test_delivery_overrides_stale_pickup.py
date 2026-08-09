from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard, merge_order_state
from amelia_manager.order_policy import get_next_step
from amelia_manager.order_state import extract_order_state
from amelia_manager.telegram_runtime import update_active_order_from_messages


def test_explicit_delivery_address_overrides_stale_pickup_card():
    existing = OrderCard(
        budget=15000,
        colors=["красный"],
        fulfillment_type="pickup",
        delivery_date="tomorrow",
        delivery_time="23:00",
        sender_name="Даниил",
        sender_phone="89990000005",
    )
    state = extract_order_state(["Клиент: нужна доставка на Гайдара 173"])

    merged = merge_order_state(existing, state)
    step = get_next_step(merged)

    assert merged.fulfillment_type == "delivery"
    assert merged.address == "Гайдара 173"
    assert merged.delivery_time is None
    assert step.code != "ask_pickup_time_within_shop_hours"
    assert "самовывоз" not in step.instruction.lower()


def test_runtime_explicit_delivery_address_overrides_active_pickup_order(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(
        order_id=order.id,
        card=OrderCard(
            budget=15000,
            colors=["красный"],
            fulfillment_type="pickup",
            delivery_date="tomorrow",
            delivery_time="23:00",
            sender_name="Даниил",
            sender_phone="89990000005",
        ),
    )

    card = update_active_order_from_messages(
        repo,
        client_id=client.id,
        recent_messages=["Клиент: нужна доставка на Гайдара 173"],
    )

    assert card.fulfillment_type == "delivery"
    assert card.address == "Гайдара 173"
    assert card.delivery_time is None


def test_mixed_history_switch_to_delivery_clears_old_pickup_time(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(
        order_id=order.id,
        card=OrderCard(
            budget=15000,
            colors=["красный"],
            fulfillment_type="pickup",
            delivery_date="tomorrow",
            delivery_time="23:00",
            sender_name="Даниил",
            sender_phone="89990000005",
        ),
    )

    card = update_active_order_from_messages(
        repo,
        client_id=client.id,
        recent_messages=[
            "Клиент: Самовывоз",
            "Клиент: Завтра в 23:00",
            "Менеджер: Самовывоз возможен в часы работы магазина с 09:00 до 20:00",
            "Клиент: Нужна доставка на Гайдара 173",
        ],
    )

    assert card.fulfillment_type == "delivery"
    assert card.address == "Гайдара 173"
    assert card.delivery_time is None
