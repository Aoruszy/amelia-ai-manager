from amelia_manager.company_profile import CompanyProfile
from amelia_manager.conversation_engine import _cautious_reply_for_medium_risk
from amelia_manager.risk import RiskCategory, RiskLevel, assess_risk


def test_stock_uncertainty_terms_come_from_profile_not_florist_core():
    cafe = CompanyProfile(
        company_name="Coffee Test",
        manager_name="Оля",
        business_type="cafe",
        city="Калининград",
        tone="короткий",
        stock_terms=("зерно", "круассан"),
        alternative_offer_text="могу предложить другой напиток",
    )

    assert assess_risk("Есть пионы?", company_profile=cafe).level == RiskLevel.LOW
    coffee_risk = assess_risk("Есть зерно в наличии?", company_profile=cafe)
    assert coffee_risk.level == RiskLevel.MEDIUM
    assert coffee_risk.category == RiskCategory.STOCK_UNCERTAINTY


def test_medium_stock_cautious_reply_uses_profile_alternative_text():
    cafe = CompanyProfile(
        company_name="Coffee Test",
        manager_name="Оля",
        business_type="cafe",
        city="Калининград",
        tone="короткий",
        alternative_offer_text="могу предложить другой напиток",
    )

    reply = _cautious_reply_for_medium_risk(
        RiskCategory.STOCK_UNCERTAINTY,
        stock_context=None,
        company_profile=cafe,
    )

    assert "другой напиток" in reply
    assert "букет" not in reply
    assert "стил" not in reply


def test_medium_stock_cautious_reply_handles_explicit_unavailable_stock_context_without_handoff():
    reply = _cautious_reply_for_medium_risk(
        RiskCategory.STOCK_UNCERTAINTY,
        stock_context="По наличию на сегодня релевантно:\n- пионы — нет",
    )

    assert reply is not None
    assert "пионы" in reply.lower()
    assert "нет" in reply.lower()
    assert "менеджер" not in reply.lower()
