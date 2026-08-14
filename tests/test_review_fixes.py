from __future__ import annotations

import json
from datetime import date

import pytest

from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.conversation_engine import ConversationEngine, _format_order_card_context
from amelia_manager.order_card import OrderCard, applied_order_patch_field_codes, merge_order_patch, unapplied_order_patch_field_codes
from amelia_manager.order_extractor import extract_order_state_with_llm
from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskCategory, RiskLevel, assess_risk


class FakeLLM:
    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **kwargs) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("unexpected LLM call")
        return self.responses.pop(0)


def test_high_risk_wins_over_profile_stock_marker_and_product_mentions():
    cases = [
        ("Мне привезли не то, там были пионы, верните деньги", RiskCategory.COMPLAINT_REFUND),
        ("Хочу пожаловаться, пионы завяли на второй день", RiskCategory.COMPLAINT_REFUND),
        ("Я оплатила, пионы забрала", RiskCategory.PAYMENT_CONFIRMATION_WITHOUT_MANAGER),
    ]

    for text, category in cases:
        risk = assess_risk(text, company_profile=load_company_profile())
        assert risk.level == RiskLevel.HIGH
        assert risk.category == category


def test_stock_uncertainty_uses_availability_markers_not_product_names():
    profile = load_company_profile()

    in_stock = assess_risk("Пионы точно есть в наличии?", company_profile=profile)
    product_only = assess_risk("Хочу пионы на завтра", company_profile=profile)

    assert in_stock.level == RiskLevel.MEDIUM
    assert in_stock.category == RiskCategory.STOCK_UNCERTAINTY
    assert product_only.category != RiskCategory.STOCK_UNCERTAINTY


def test_profile_stock_marker_field_has_single_semantics_for_non_florist_profiles():
    cafe = CompanyProfile(
        company_name="Coffee Test",
        manager_name="Оля",
        business_type="cafe",
        city="Калининград",
        tone="короткий",
        stock_question_markers=("в наличии",),
    )

    assert assess_risk("Есть зерно?", company_profile=cafe).level == RiskLevel.LOW
    risk = assess_risk("Зерно точно есть в наличии?", company_profile=cafe)
    assert risk.category == RiskCategory.STOCK_UNCERTAINTY


def test_merge_order_patch_accepts_profile_field_aliases_and_native_names():
    card = OrderCard(budget=5000)
    patch = {
        "product_preferences": ["розы"],
        "date": "2026-08-20",
        "time": "14:00",
        "delivery_address": "ул. Ленина 12",
        "customer_name": "Иван",
        "customer_phone": "+79001234567",
        "payment_method": "cash",
    }

    merged = merge_order_patch(card, patch)
    native = merge_order_patch(OrderCard(), {"colors": ["белые"], "delivery_date": "2026-08-21"})

    assert merged.colors == ["розы"]
    assert merged.delivery_date == "2026-08-20"
    assert merged.delivery_time == "14:00"
    assert merged.address == "ул. Ленина 12"
    assert merged.sender_name == "Иван"
    assert merged.sender_phone == "+79001234567"
    assert merged.payment_method == "cash"
    assert native.colors == ["белые"]
    assert native.delivery_date == "2026-08-21"


def test_applied_order_patch_field_codes_report_only_actual_changes():
    before = OrderCard(budget=5000)
    after_unknown = merge_order_patch(before, {"погода": "хорошая"})
    after_empty = merge_order_patch(before, {"date": "", "customer_name": None})
    after_valid = merge_order_patch(before, {"date": "2026-08-20", "customer_name": "Иван"})

    assert applied_order_patch_field_codes(before, after_unknown, {"погода": "хорошая"}) == []
    assert unapplied_order_patch_field_codes({"погода": "хорошая"}) == ["погода"]
    assert applied_order_patch_field_codes(before, after_empty, {"date": "", "customer_name": None}) == []
    assert applied_order_patch_field_codes(before, after_valid, {"date": "2026-08-20", "customer_name": "Иван"}) == ["date", "customer_name"]


@pytest.mark.asyncio
async def test_llm_budget_wins_over_greedy_regex_dates_order_numbers_and_house_numbers():
    state = await extract_order_state_with_llm(
        FakeLLM('{"budget":5000,"delivery_date":"2026-03-15","address":"ул. Тестовая, 3456"}'),
        ["Клиент: бюджет 5000, доставка 15.03.2026, дом 3456, заказ номер 12345"],
        today=date(2026, 1, 1),
    )

    assert state.budget == 5000
    assert state.budget not in {2026, 3456, 12345}


@pytest.mark.asyncio
async def test_budget_regex_still_extracts_explicit_budget_when_llm_unavailable():
    state = await extract_order_state_with_llm(FakeLLM("не json"), ["Клиент: бюджет до 5 тысяч"], today=date(2026, 1, 1))

    assert state.budget == 5000


@pytest.mark.asyncio
async def test_sensitive_parse_retry_suppresses_emoji_when_retry_succeeds():
    llm = FakeLLM(
        '{"reply":"сырой json", "case_patch":',
        json.dumps({
            "intent": "order",
            "emotion": "grief",
            "reply": "Поняла. Подготовим сдержанно 🌸",
            "case_patch": {},
            "next_step": "ask_budget",
            "needs_human": False,
            "confidence": 0.9,
        }, ensure_ascii=False),
    )
    card = OrderCard(custom_fields={"occasion_sensitive": True})

    action = await ConversationEngine(llm).handle_messages(
        client_summary="скорбный повод",
        recent_messages=["Клиент: хорошо"],
        stage="new",
        order_card=card,
    )

    assert action.kind == "send"
    assert "🌸" not in action.messages[0]


@pytest.mark.asyncio
async def test_sensitive_parse_retry_handoffs_for_forbidden_word_in_retry_reply():
    llm = FakeLLM(
        '{"reply":"сырой json", "case_patch":',
        json.dumps({
            "intent": "order",
            "emotion": "grief",
            "reply": "Сделаем нежный вариант",
            "case_patch": {},
            "next_step": "ask_budget",
            "needs_human": False,
            "confidence": 0.9,
        }, ensure_ascii=False),
    )
    card = OrderCard(custom_fields={"occasion_sensitive": True})

    action = await ConversationEngine(llm).handle_messages(
        client_summary="скорбный повод",
        recent_messages=["Клиент: хорошо"],
        stage="new",
        order_card=card,
    )

    assert action.kind == "human_review"
    assert "нежн" not in action.messages[0].lower()


def test_sensitive_prompt_hides_forbidden_preference_words_from_order_context():
    profile = load_company_profile()
    card = OrderCard(colors=["нежный стиль", "яркий стиль"], custom_fields={"occasion_sensitive": True})

    prompt = build_manager_prompt(
        client_summary="скорбный повод",
        recent_messages=["Клиент: хорошо"],
        stage="new",
        risk_level=RiskLevel.MEDIUM,
        order_card_context="",
        sensitive_occasion=True,
        company_profile=profile,
    )
    prompt_with_context = build_manager_prompt(
        client_summary="скорбный повод",
        recent_messages=["Клиент: хорошо"],
        stage="new",
        risk_level=RiskLevel.MEDIUM,
        order_card_context=_format_order_card_context(card, sensitive_occasion=True, company_profile=profile),
        sensitive_occasion=True,
        company_profile=profile,
    )

    for forbidden in profile.sensitive_occasion_forbidden_words:
        assert forbidden not in prompt.lower()
        assert forbidden not in prompt_with_context.lower()


def test_regular_prompt_keeps_regular_style_words_in_order_context():
    profile = load_company_profile()
    card = OrderCard(colors=["нежный стиль"])
    context = _format_order_card_context(card, sensitive_occasion=False, company_profile=profile)

    assert "нежный стиль" in context.lower()
