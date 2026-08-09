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
