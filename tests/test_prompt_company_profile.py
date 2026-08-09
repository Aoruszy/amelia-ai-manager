from amelia_manager.company_profile import BusinessField, CompanyProfile
from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskLevel


def test_prompt_uses_injected_company_profile_instead_of_hardcoded_amelia():
    profile = CompanyProfile(
        company_name="Dental Plus",
        manager_name="Марина",
        business_type="clinic",
        city="Калининград",
        tone="спокойный, заботливый, без медицинских обещаний",
        services=["чистка зубов", "лечение", "консультация"],
        required_fields={
            "appointment": [
                BusinessField("service", "услуга"),
                BusinessField("date", "дата"),
                BusinessField("customer_phone", "телефон"),
            ]
        },
        business_rules=["не ставить диагноз по переписке", "не обещать лечение без осмотра"],
    )

    prompt = build_manager_prompt(
        client_summary="Новый клиент",
        recent_messages=["Клиент: Хочу записаться на чистку"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
        company_profile=profile,
    )

    assert "Ты — Марина" in prompt
    assert "Dental Plus" in prompt
    assert "clinic" in prompt
    assert "чистка зубов" in prompt
    assert "не ставить диагноз по переписке" in prompt
    assert "Amelia Flowers" not in prompt
    assert "цветочного магазина" not in prompt


def test_prompt_includes_profile_product_categories_and_faq():
    profile = CompanyProfile(
        company_name="Test Flowers",
        manager_name="Алина",
        business_type="florist",
        city="Калининград",
        tone="коротко",
        services=["букеты"],
        product_categories=("монобукеты", "корзины"),
        faq={"anonymous": "Анонимная доставка возможна, если имя отправителя не указано в открытке."},
    )

    prompt = build_manager_prompt(
        client_summary="Новый клиент",
        recent_messages=["Клиент: Можно анонимно доставить?"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
        company_profile=profile,
    )

    assert "монобукеты" in prompt
    assert "корзины" in prompt
    assert "Анонимная доставка возможна" in prompt
