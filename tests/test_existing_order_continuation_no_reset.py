from amelia_manager.order_card import OrderCard
from amelia_manager.telegram_runtime import should_start_new_order


def test_regular_order_continuation_does_not_reset_active_order():
    card = OrderCard(budget=5000, colors=["розовый"], fulfillment_type="pickup")

    assert should_start_new_order("Оплачу на месте", card) is False
    assert should_start_new_order("Даниил 89990000005", card) is False
    assert should_start_new_order("18:00", card) is False
