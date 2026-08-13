from amelia_manager.client_order_summary import format_client_order_summary
from amelia_manager.order_card import OrderCard, format_budget_display
from amelia_manager.order_request import format_admin_order_request


def test_budget_range_display_prefers_custom_range():
    card = OrderCard(budget=7000, custom_fields={"budget_range": "5000-7000"})

    assert format_budget_display(card) == "5000–7000 ₽"


def test_client_summary_shows_budget_range():
    card = OrderCard(
        budget=7000,
        colors=["нежный стиль"],
        fulfillment_type="pickup",
        delivery_date="2026-08-14",
        delivery_time="18:00",
        sender_name="Даня",
        sender_phone="89990000000",
        custom_fields={"budget_range": "5000-7000"},
    )

    text = format_client_order_summary(card)

    assert "5000–7000 ₽" in text
    assert "Бюджет: 7000 ₽" not in text


def test_admin_request_shows_budget_range():
    card = OrderCard(
        budget=7000,
        colors=["нежный стиль"],
        fulfillment_type="pickup",
        delivery_date="2026-08-14",
        delivery_time="18:00",
        sender_name="Даня",
        sender_phone="89990000000",
        custom_fields={"budget_range": "5000-7000"},
    )

    text = format_admin_order_request(order_id=1, client_label="client", card=card)

    assert "Бюджет: 5000–7000 ₽" in text
