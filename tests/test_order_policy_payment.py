from amelia_manager.order_policy import get_next_step
from amelia_manager.order_state import OrderState


def test_pickup_with_payment_method_confirms_order_instead_of_asking_payment_again():
    state = OrderState(
        budget=5000,
        colors=["синий", "белый"],
        fulfillment_type="pickup",
        delivery_date="today",
        delivery_time="18:00",
        sender_name="Даниил",
        sender_phone="89990000006",
        payment_method="transfer",
    )

    step = get_next_step(state)

    assert step.code == "confirm_pickup_order"
    assert "Уточни удобный способ оплаты" not in step.instruction
