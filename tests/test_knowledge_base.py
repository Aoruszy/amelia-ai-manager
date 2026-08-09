from amelia_manager.company_profile import load_company_profile
from amelia_manager.knowledge_base import get_faq_answer, get_store_facts


def test_store_facts_include_core_amelia_details():
    profile = load_company_profile("amelia_flowers")
    facts = get_store_facts()

    assert facts.name == profile.company_name
    assert facts.city == profile.city
    assert facts.address == profile.pickup_address
    assert facts.manager_name == profile.manager_name
    assert facts.delivery_city_price == profile.delivery_city_price
    assert facts.free_delivery_from == profile.free_delivery_from
    assert facts.delivery_hours == profile.delivery_hours


def test_delivery_faq_mentions_free_threshold_and_city_price():
    answer = get_faq_answer("delivery")

    assert "400" in answer
    assert "5000" in answer
    assert "от 1 часа" in answer


def test_anonymous_faq_says_recipient_only_knows_if_postcard_contains_name():
    answer = get_faq_answer("anonymous")

    assert "аноним" in answer.lower()
    assert "открытк" in answer.lower()


def test_unknown_faq_returns_none():
    assert get_faq_answer("unknown-topic") is None
