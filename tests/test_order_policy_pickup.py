from amelia_manager.order_policy import get_next_step
from amelia_manager.order_state import OrderState


def test_pickup_order_does_not_require_recipient_contacts():
    state = OrderState(
        budget=5000,
        colors=["синий", "белый"],
        fulfillment_type="pickup",
        delivery_date="today",
        delivery_time="18:00",
        sender_name="Даниил",
        sender_phone="89990000006",
    )

    step = get_next_step(state)

    assert step.code == "confirm_pickup_order"
    assert "получател" not in step.instruction.lower()
    assert "уточни удобный способ оплаты" not in step.instruction.lower()


def test_pickup_without_time_asks_pickup_time_not_delivery_time():
    state = OrderState(
        budget=5000,
        colors=["синий"],
        fulfillment_type="pickup",
        delivery_date="today",
    )

    step = get_next_step(state)

    assert step.code == "ask_pickup_time"
    assert "забрать" in step.instruction.lower()
