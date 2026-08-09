from amelia_manager.client_order_summary import format_client_order_summary
from amelia_manager.order_card import OrderCard


def test_pickup_summary_without_payment_does_not_show_missing_payment_line():
    text = format_client_order_summary(
        OrderCard(
            budget=15000,
            colors=["нежный"],
            fulfillment_type="pickup",
            delivery_date="tomorrow",
            delivery_time="18:00",
            sender_name="Даниил",
            sender_phone="89990000005",
        )
    )

    assert "Оплата: не указана" not in text
    assert "способ оплаты" not in text.lower()
    assert "менеджер" in text.lower()
