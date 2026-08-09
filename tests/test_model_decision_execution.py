import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.order_card import OrderCard, merge_order_patch
from amelia_manager.telegram_runtime import derive_client_state


class DecisionLLM:
    async def generate(self, prompt: str) -> str:
        return '{"intent":"order_update","reply":"Записала бюджет 7000.","case_patch":{"budget":7000,"fulfillment_type":"pickup"},"next_step":"ask_date","confidence":0.82,"needs_human":false}'


class LowConfidenceLLM:
    async def generate(self, prompt: str) -> str:
        return '{"intent":"uncertain","reply":"Я не уверена, передам менеджеру.","case_patch":{"budget":7000},"confidence":0.34,"needs_human":false}'


@pytest.mark.asyncio
async def test_model_decision_case_patch_is_exposed_for_runtime_merge():
    action = await ConversationEngine(DecisionLLM()).handle_messages(
        client_summary="",
        recent_messages=["Клиент: бюджет 7000, самовывоз"],
        stage="new_lead",
    )

    assert action.kind == "send"
    assert action.messages == ["Записала бюджет 7000."]
    assert action.order_patch == {"budget": 7000, "fulfillment_type": "pickup"}
    assert action.intent == "order_update"
    assert action.next_step == "ask_date"
    assert action.confidence == 0.82
    assert merge_order_patch(OrderCard(), action.order_patch).budget == 7000
    assert merge_order_patch(OrderCard(), action.order_patch).fulfillment_type == "pickup"


@pytest.mark.asyncio
async def test_low_confidence_model_decision_escalates_without_merging_patch():
    action = await ConversationEngine(LowConfidenceLLM()).handle_messages(
        client_summary="",
        recent_messages=["Клиент: что-то непонятное"],
        stage="new_lead",
    )

    assert action.kind == "human_review"
    assert action.order_patch == {}
    assert "low_model_confidence" in action.safety_reasons


def test_derive_client_state_uses_order_progress_and_summary():
    stage, summary = derive_client_state(
        OrderCard(budget=7000, colors=["белый"], fulfillment_type="pickup", delivery_date="2026-08-10"),
        last_client_text="Нужен белый букет до 7000 самовывоз завтра",
    )

    assert stage == "order_in_progress"
    assert "7000" in summary
    assert "самовывоз" in summary
    assert "белый" in summary
