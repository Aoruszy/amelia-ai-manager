from amelia_manager.knowledge_base import get_faq_answer, get_store_facts


def test_store_facts_include_core_amelia_details():
    facts = get_store_facts()

    assert facts.name == "Amelia Flowers"
    assert facts.city == "Калининград"
    assert "Сергеева 61" in facts.address
    assert facts.manager_name == "Алина"
    assert facts.delivery_city_price == 400
    assert facts.free_delivery_from == 5000
    assert facts.delivery_hours == "08:00–22:00"


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
