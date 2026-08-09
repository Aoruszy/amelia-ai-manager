from amelia_manager.order_card import OrderCard
from amelia_manager.telegram_runtime import should_start_new_order


def test_buy_flow_phrase_starts_new_order_after_completed_order():
    completed = OrderCard(
        budget=10000,
        colors=["белый"],
        fulfillment_type="pickup",
        delivery_date="12 августа",
        delivery_time="12:00",
        sender_name="Даниил",
        sender_phone="89990000005",
        payment_method="cash",
        admin_request_sent=True,
        client_summary_sent=True,
    )

    assert should_start_new_order("Хочу цветы купить", completed) is True
    assert should_start_new_order("Хочу букет купить", completed) is True
