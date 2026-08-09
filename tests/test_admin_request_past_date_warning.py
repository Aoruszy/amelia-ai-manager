from amelia_manager.order_card import OrderCard
from amelia_manager.order_request import format_admin_order_request


def test_admin_request_highlights_explicit_past_delivery_date():
    text = format_admin_order_request(
        order_id=1,
        client_label="@dummy / 123",
        card=OrderCard(
            budget=5000,
            colors=["розы"],
            fulfillment_type="pickup",
            delivery_date="2026-03-08",
            delivery_time="18:00",
            sender_name="Даниил",
            sender_phone="89990000001",
        ),
    )

    assert "2026-03-08" in text
    assert "дата в прошлом" in text
