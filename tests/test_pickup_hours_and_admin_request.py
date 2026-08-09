from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard
from amelia_manager.order_policy import get_next_step
from amelia_manager.order_state import OrderState
from amelia_manager.telegram_runtime import build_admin_order_request_if_needed


def test_pickup_at_23_00_asks_for_time_within_shop_hours_before_contacts():
    state = OrderState(
        budget=15000,
        colors=["нежный"],
        fulfillment_type="pickup",
        delivery_date="tomorrow",
        delivery_time="23:00",
    )

    step = get_next_step(state)

    assert step.code == "ask_pickup_time_within_shop_hours"
    assert "09:00" in step.instruction
    assert "20:00" in step.instruction
    assert "имя" not in step.instruction.lower()
    assert "телефон" not in step.instruction.lower()


def test_pickup_order_ready_for_admin_without_payment_method():
    card = OrderCard(
        budget=15000,
        colors=["нежный"],
        fulfillment_type="pickup",
        delivery_date="tomorrow",
        delivery_time="18:00",
        sender_name="Даниил",
        sender_phone="89990000005",
    )

    assert card.is_ready_for_admin_request() is True


def test_pickup_without_payment_builds_admin_request_once(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")
    order = repo.get_or_create_active_order(client_id=client.id)
    card = OrderCard(
        budget=15000,
        colors=["нежный"],
        fulfillment_type="pickup",
        delivery_date="tomorrow",
        delivery_time="18:00",
        sender_name="Даниил",
        sender_phone="89990000005",
    )
    repo.update_order_card(order_id=order.id, card=card)
    order = repo.get_active_order(client_id=client.id)

    first = build_admin_order_request_if_needed(repo, order=order, client_label="@client / 123")
    second = build_admin_order_request_if_needed(
        repo,
        order=repo.get_active_order(client_id=client.id),
        client_label="@client / 123",
    )

    assert first is not None
    assert "Самовывоз" in first
    assert second is None
