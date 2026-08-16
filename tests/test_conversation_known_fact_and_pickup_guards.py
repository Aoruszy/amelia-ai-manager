import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.client_order_summary import format_client_order_summary
from amelia_manager.order_card import OrderCard


class StaticLLM:
    async def generate(self, prompt: str, **kwargs) -> str:
        return "Поняла. Подскажите, пожалуйста, недостающие детали заказа?"


@pytest.mark.asyncio
async def test_delivery_price_question_uses_profile_fact_without_catalog_context():
    action = await ConversationEngine(StaticLLM()).handle_messages(
        client_summary="Eval клиент",
        recent_messages=["Клиент: Сколько стоит доставка по городу?"],
        stage="eval",
        stock_context="",
    )

    text = "\n".join(action.messages)
    assert "400" in text
    assert "5000" in text
    assert "уточню у менеджера" not in text.lower()


@pytest.mark.asyncio
async def test_pickup_time_outside_hours_uses_deterministic_guard_before_llm_reply():
    action = await ConversationEngine(StaticLLM()).handle_messages(
        client_summary="Eval клиент",
        recent_messages=["Клиент: Букет до 4000, нежный, самовывоз сегодня в 22:30"],
        stage="eval",
    )

    text = "\n".join(action.messages)
    assert action.next_step == "ask_pickup_time_within_shop_hours"
    assert "22:30" in text
    assert "09:00" in text
    assert "20:00" in text


def test_pickup_summary_mentions_no_payment_when_payment_not_collected():
    action_text = format_client_order_summary(
        OrderCard(
            budget=5000,
            colors=["розовый"],
            fulfillment_type="pickup",
            delivery_date="2026-08-20",
            delivery_time="14:00",
            sender_name="Олег",
            sender_phone="89990000007",
        )
    )

    assert "оплат" not in action_text.lower()
