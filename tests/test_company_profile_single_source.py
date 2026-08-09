from amelia_manager.company_profile import BusinessField, CompanyProfile, load_company_profile
from amelia_manager.knowledge_base import get_faq_answer, get_store_facts
from amelia_manager.order_card import OrderCard
from amelia_manager.order_request import format_admin_order_request
from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskLevel


def test_knowledge_base_store_facts_are_derived_from_company_profile():
    profile = load_company_profile("amelia_flowers")
    facts = get_store_facts(profile)

    assert facts.name == profile.company_name
    assert facts.manager_name == profile.manager_name
    assert facts.city == profile.city
    assert facts.address == profile.pickup_address
    assert facts.phone == profile.public_phone
    assert facts.shop_hours == profile.shop_hours
    assert facts.delivery_hours == profile.delivery_hours
    assert facts.delivery_city_price == profile.delivery_city_price
    assert facts.free_delivery_from == profile.free_delivery_from


def test_delivery_faq_uses_profile_delivery_prices_and_nearest_time():
    profile = load_company_profile("amelia_flowers")

    answer = get_faq_answer("delivery", profile)

    assert str(profile.delivery_city_price) in answer
    assert str(profile.free_delivery_from) in answer
    assert profile.nearest_delivery_time in answer


def test_prompt_uses_profile_facts_not_amelia_knowledge_base_defaults():
    profile = CompanyProfile(
        company_name="Bakery One",
        manager_name="Оля",
        business_type="bakery",
        city="Калининград",
        tone="короткий и дружелюбный",
        services=["торты"],
        required_fields={"order": [BusinessField("date", "дата")]},
        business_rules=["не обещать срочную доставку без подтверждения"],
        pickup_address="ул. Тестовая, 5",
        public_phone="+7 (999) 000-00-01",
        shop_hours="10:00–18:00",
        delivery_hours="11:00–17:00",
        free_delivery_from=3000,
        delivery_city_price=250,
        nearest_delivery_time="от 3 часов после оформления",
    )

    prompt = build_manager_prompt(
        client_summary="Новый клиент",
        recent_messages=["Клиент: нужен торт"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
        company_profile=profile,
    )

    assert "Bakery One" in prompt
    assert "ул. Тестовая, 5" in prompt
    assert "+7 (999) 000-00-01" in prompt
    assert "до 3000 ₽ стоит 250 ₽" in prompt
    assert "Сергеева" not in prompt
    assert "+7 (952)" not in prompt


def test_admin_order_request_uses_profile_name_and_pickup_address():
    profile = load_company_profile("amelia_flowers")
    text = format_admin_order_request(
        order_id=1,
        client_label="@client / 123",
        company_profile=profile,
        card=OrderCard(
            budget=5000,
            colors=["белый"],
            fulfillment_type="pickup",
            delivery_date="today",
            delivery_time="18:00",
            sender_name="Даниил",
            sender_phone="89990000006",
        ),
    )

    assert f"Новая заявка {profile.company_name}" in text
    assert f"Самовывоз: {profile.pickup_address}" in text
