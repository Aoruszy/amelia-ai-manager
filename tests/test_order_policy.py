from amelia_manager.order_policy import get_next_step
from amelia_manager.order_state import OrderState


def test_next_step_asks_fulfillment_before_delivery_address():
    state = OrderState(occasion="девушке", budget=7000, colors=["синий", "белый"], delivery_date="today", delivery_time="18:00")

    step = get_next_step(state)

    assert step.code == "ask_fulfillment_type"
    assert "доставка или самовывоз" in step.instruction
    assert "адрес" not in step.instruction.lower()


def test_next_step_asks_address_only_after_delivery_chosen():
    state = OrderState(fulfillment_type="delivery", budget=7000, colors=["синий"], delivery_date="today", delivery_time="18:00")

    step = get_next_step(state)

    assert step.code == "ask_delivery_address"
    assert "адрес" in step.instruction.lower()


def test_next_step_after_address_and_contacts_asks_anonymous_or_payment_not_handoff():
    state = OrderState(
        fulfillment_type="delivery",
        delivery_date="today",
        delivery_time="18:00",
        address="Гайдара 173",
        sender_name="Даниил",
        sender_phone="89990000007",
        recipient_name="Ольга",
        recipient_phone="89990000008",
        budget=7000,
        colors=["синий", "белый"],
    )

    step = get_next_step(state)

    assert step.code == "ask_anonymous_or_payment"
    assert "ответственному менеджеру" not in step.instruction.lower()
