import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.order_card import OrderCard
from amelia_manager.order_policy import get_next_step
from amelia_manager.order_state import OrderState, extract_order_state


class CapturingLLM:
    def __init__(self):
        self.prompt = ""

    async def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return "Подскажите, какие оттенки или цветы больше нравятся?"


def test_budget_and_occasion_do_not_trigger_fulfillment_before_bouquet_preferences():
    state = OrderState(budget=5000, occasion="девушке")

    step = get_next_step(state)

    assert step.code == "ask_bouquet_preferences"
    assert "нужна доставка" not in step.instruction.lower()
    assert "клиенту нужна доставка" not in step.instruction.lower()


def test_payment_on_site_is_cash_payment_method():
    state = extract_order_state(["Клиент: Оплачу на месте", "Клиент: оплата при получении"])

    assert state.payment_method == "cash"


@pytest.mark.asyncio
async def test_ready_pickup_order_returns_final_summary_to_client():
    engine = ConversationEngine(CapturingLLM())

    action = await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: 18:00"],
        stage="new_lead",
        order_card=OrderCard(
            budget=5000,
            colors=["розовый", "желтый", "белый"],
            fulfillment_type="pickup",
            delivery_date="today",
            delivery_time="18:00",
            sender_name="Даниил",
            sender_phone="89990000005",
            payment_method="cash",
        ),
    )

    joined = "\n".join(action.messages)
    assert action.kind == "send"
    assert "Итог заказа" in joined
    assert "Самовывоз" in joined
    assert "18:00" in joined
    assert "5000" in joined
