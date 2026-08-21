from amelia_manager.company_profile import load_company_profile
from amelia_manager.order_card import OrderCard
from amelia_manager.safety import check_reply_safety, safety_retry_guidance_for_reasons


def test_retry_prompt_has_allowed_alternative_for_each_known_reason():
    reasons = [
        "unsupported_price_quote",
        "unverified_stock_promise",
        "stock_context_contradiction",
        "exact_delivery_guarantee",
        "unsupported_photo_promise",
        "unsupported_handoff_promise",
        "payment_confirmation_without_manager",
        "shop_address_as_delivery",
        "pickup_recipient_question",
        "identity_disclosure",
    ]

    guidance = safety_retry_guidance_for_reasons(reasons)

    assert len([line for line in guidance.splitlines() if line.strip()]) == len(reasons)
    assert "примерно" in guidance
    assert "наличие обещать нельзя" in guidance
    assert "не упоминать, что ты программа" in guidance


def test_retry_prompt_handles_sensitive_reason_by_prefix():
    guidance = safety_retry_guidance_for_reasons(["запрещённые слова для чувствительного повода: нежный"])

    assert "без эмодзи" in guidance
    assert "без слова «нежный»" in guidance


def test_retry_prompt_ignores_unknown_reasons_without_blank_lines():
    guidance = safety_retry_guidance_for_reasons(["unknown_reason"])

    assert guidance == ""


def test_client_budget_amount_is_safe_only_when_reply_frames_it_as_budget():
    card = OrderCard(budget=6000)
    allowed = [
        "Соберу букет в рамках вашего бюджета 6000 ₽",
        "В пределах 6000 ₽ подберу вариант",
        "Ориентируюсь на бюджет до 6000 ₽",
        "Букет обойдётся примерно в 5500–6000 ₽",
    ]
    blocked = [
        "Стоимость букета 6000 ₽",
        "Цена букета — 6000 ₽",
        "Букет стоит 4500 ₽",
    ]

    for reply in allowed:
        assert check_reply_safety(reply, order_card=card, company_profile=load_company_profile()).is_safe, reply
    for reply in blocked:
        result = check_reply_safety(reply, order_card=card, company_profile=load_company_profile())
        assert result.is_safe is False, reply
        assert "unsupported_price_quote" in result.reasons


def test_empty_card_does_not_allow_arbitrary_price_quote():
    result = check_reply_safety("Соберу букет в рамках вашего бюджета 6000 ₽", order_card=OrderCard())

    assert result.is_safe is False
    assert "unsupported_price_quote" in result.reasons
