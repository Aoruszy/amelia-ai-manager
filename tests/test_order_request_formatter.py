from amelia_manager.order_card import OrderCard
from amelia_manager.order_request import format_admin_order_request


def test_format_admin_order_request_for_pickup():
    text = format_admin_order_request(
        order_id=15,
        client_label="@client / 123",
        card=OrderCard(
            budget=5000,
            colors=["синий", "белый"],
            fulfillment_type="pickup",
            delivery_date="today",
            delivery_time="18:00",
            sender_name="Даниил",
            sender_phone="89990000006",
            payment_method="transfer",
        ),
    )

    assert "Новая заявка Amelia Flowers" in text
    assert "Тип: самовывоз" in text
    assert "Даниил" in text
    assert "5000" in text
    assert "синий, белый" in text
