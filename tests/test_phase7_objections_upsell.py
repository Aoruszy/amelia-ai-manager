import pytest

from amelia_manager.company_profile import load_company_profile
from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.order_card import OrderCard
from amelia_manager.order_policy import get_next_step
from amelia_manager.order_state import OrderState
from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskCategory, RiskLevel, assess_risk


class ShouldNotCallLLM:
    async def generate(self, prompt: str) -> str:  # pragma: no cover - should not be called
        raise AssertionError("LLM should not be called for deterministic objection fallback")


class UpsellDecisionLLM:
    async def generate(self, prompt: str) -> str:
        return (
            '{"reply":"Можно добавить открытку, вазу или шарики — нужно что-то из этого?",'
            '"intent":"order","next_step":"ask_upsell","case_patch":{},'
            '"confidence":0.9,"order_scope":"continue"}'
        )


def _ready_without_contacts(**custom_fields) -> OrderCard:
    return OrderCard(
        budget=5000,
        colors=["пастельный"],
        fulfillment_type="pickup",
        delivery_date="завтра",
        delivery_time="14:00",
        custom_fields=custom_fields,
    )


def test_expensive_objection_is_medium_discount_risk():
    risk = assess_risk("Дороговато выходит", company_profile=load_company_profile())

    assert risk.level == RiskLevel.MEDIUM
    assert risk.category == RiskCategory.DISCOUNT


@pytest.mark.asyncio
async def test_expensive_objection_offers_cheaper_same_style_without_discount():
    action = await ConversationEngine(ShouldNotCallLLM()).handle_messages(
        client_summary="новый клиент",
        recent_messages=["Клиент: дороговато, можно дешевле такой же?"],
        stage="collecting",
    )

    reply = action.messages[0].lower()
    assert action.kind == "send"
    assert "подбер" in reply or "вариант" in reply
    assert "дешев" in reply or "бюджет" in reply
    assert "скид" not in reply
    assert "менеджер" not in reply


def test_prompt_contains_profile_owned_objection_and_upsell_rules():
    profile = load_company_profile()
    prompt = build_manager_prompt(
        client_summary="новый клиент",
        recent_messages=["Клиент: Букет до 5000"],
        stage="collecting",
        risk_level=RiskLevel.LOW,
        company_profile=profile,
    )

    assert "дороговато" in prompt.lower()
    assert "никогда не давай скидку" in prompt.lower()
    for offer in profile.upsell_offers:
        assert offer.name in prompt
        assert str(offer.price) in prompt


def test_next_step_offers_upsell_once_before_contacts():
    profile = load_company_profile()
    step = get_next_step(_ready_without_contacts(), company_profile=profile)

    assert step.code == "ask_upsell"
    assert "один раз" in step.instruction.lower()
    assert "открыт" in step.instruction.lower()


def test_next_step_skips_upsell_when_already_offered_or_sensitive():
    profile = load_company_profile()

    already_offered = get_next_step(_ready_without_contacts(upsell_offered=True), company_profile=profile)
    sensitive = get_next_step(_ready_without_contacts(occasion_sensitive=True), company_profile=profile)

    assert already_offered.code == "ask_sender_contacts"
    assert sensitive.code == "ask_sender_contacts"


@pytest.mark.asyncio
async def test_upsell_step_uses_deterministic_profile_offer_without_llm():
    action = await ConversationEngine(ShouldNotCallLLM()).handle_messages(
        client_summary="новый клиент",
        recent_messages=["Клиент: до 5000, пастельный букет, завтра, самовывоз к 14:00"],
        stage="collecting",
        order_card=_ready_without_contacts(),
    )

    assert action.kind == "send"
    assert action.next_step == "ask_upsell"
    assert action.order_patch == {"custom_fields": {"upsell_offered": True}}
    assert "открыт" in action.messages[0].lower()


@pytest.mark.asyncio
async def test_upsell_action_marks_offer_as_seen_once():
    action = await ConversationEngine(UpsellDecisionLLM()).handle_messages(
        client_summary="новый клиент",
        recent_messages=["Клиент: до 5000, пастельный букет, завтра, самовывоз к 14:00"],
        stage="collecting",
        order_card=_ready_without_contacts(),
    )

    assert action.next_step == "ask_upsell"
    assert action.order_patch == {"custom_fields": {"upsell_offered": True}}
