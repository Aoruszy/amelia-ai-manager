from amelia_manager.client_order_summary import format_client_order_summary
from amelia_manager.company_profile import CompanyProfile
from amelia_manager.order_card import OrderCard


def test_pickup_summary_uses_company_profile_pickup_address_and_product_wording():
    profile = CompanyProfile(
        company_name="Cake Lab",
        manager_name="Оля",
        business_type="bakery",
        city="Калининград",
        tone="тёплый",
        services=["торты"],
        required_fields={},
        business_rules=[],
        pickup_address="Ленина, 10",
    )
    card = OrderCard(
        budget=3000,
        colors=["шоколадный", "ягоды"],
        fulfillment_type="pickup",
        delivery_date="tomorrow",
        delivery_time="15:00",
        sender_name="Иван",
        sender_phone="89990000010",
        payment_method="cash",
    )

    summary = format_client_order_summary(card, company_profile=profile)

    assert "Самовывоз с Ленина, 10" in summary
    assert "Сергеева" not in summary
    assert "• Заказ: шоколадный, ягоды" in summary


def test_unknown_fulfillment_summary_does_not_invent_delivery_or_pickup():
    card = OrderCard(
        budget=7000,
        colors=["розовый"],
        fulfillment_type="по согласованию",
        delivery_date="по согласованию",
        delivery_time="по согласованию",
        sender_name="Даниил",
        sender_phone="89990000002",
    )

    summary = format_client_order_summary(card)

    assert "• Формат: Доставка" not in summary
    assert "• Формат: Самовывоз" not in summary
    assert "по согласованию по согласованию" not in summary
    assert summary.count("по согласованию") == 1


def test_pickup_and_delivery_summary_format_lines_are_unchanged():
    pickup = format_client_order_summary(
        OrderCard(
            budget=5000,
            colors=["розы"],
            fulfillment_type="pickup",
            delivery_date="tomorrow",
            delivery_time="15:00",
            sender_name="Иван",
            sender_phone="89990000001",
        )
    )
    delivery = format_client_order_summary(
        OrderCard(
            budget=5000,
            colors=["розы"],
            fulfillment_type="delivery",
            delivery_date="tomorrow",
            delivery_time="15:00",
            address="ул. Тестовая, 1",
            sender_name="Иван",
            sender_phone="89990000001",
            recipient_name="Анна",
            recipient_phone="89990000002",
            payment_method="transfer",
        )
    )

    assert "• Формат: Самовывоз с Сергеева, 61" in pickup
    assert "• Формат: Доставка" in delivery
