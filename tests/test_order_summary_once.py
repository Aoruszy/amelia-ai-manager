import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.llm_client import LLMError
from amelia_manager.order_card import OrderCard
from amelia_manager.risk import RiskLevel


class FailingLLM:
    async def generate(self, prompt: str) -> str:
        raise LLMError("quota")


READY_CARD = OrderCard(
    budget=10000,
    colors=["белый", "кремовый", "нежный стиль"],
    fulfillment_type="pickup",
    delivery_date="12 августа",
    delivery_time="12:00",
    sender_name="Даниил",
    sender_phone="89990000005",
    payment_method="cash",
)


@pytest.mark.asyncio
async def test_ready_order_summary_is_sent_only_once():
    engine = ConversationEngine(FailingLLM())

    first = await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: Даниил 89990000005", "Клиент: Оплачу на месте"],
        stage="ordering",
        order_card=READY_CARD,
    )
    assert first.kind == "send"
    assert first.messages[0].startswith("Итог заказа:")

    already_summarized = OrderCard.from_dict({**READY_CARD.to_dict(), "client_summary_sent": True})
    second = await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: Спасибо"],
        stage="ordering",
        order_card=already_summarized,
    )

    assert second.kind == "send"
    assert second.messages == ["Спасибо, ждём вас 🌸"]


@pytest.mark.asyncio
async def test_complaint_after_summary_goes_to_human_takeover_not_repeat_summary():
    engine = ConversationEngine(FailingLLM())
    card = OrderCard.from_dict({**READY_CARD.to_dict(), "client_summary_sent": True})

    action = await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: Что за бред вы мне пишите !!"],
        stage="ordering",
        order_card=card,
    )

    assert action.kind == "human_takeover"
    assert action.risk_level == RiskLevel.HIGH
    assert not action.messages[0].startswith("Итог заказа:")
