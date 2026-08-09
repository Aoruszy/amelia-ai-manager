import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.order_card import OrderCard


class ShouldNotCallLLM:
    def __init__(self):
        self.prompt = ""

    async def generate(self, prompt: str) -> str:
        raise AssertionError("ready pickup order should use deterministic summary")


@pytest.mark.asyncio
async def test_engine_uses_persistent_order_card_for_next_step():
    llm = ShouldNotCallLLM()
    engine = ConversationEngine(llm)

    action = await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: сине белое можно"],
        stage="new_lead",
        order_card=OrderCard(
            budget=5000,
            colors=["синий", "белый"],
            fulfillment_type="pickup",
            delivery_date="today",
            delivery_time="18:00",
            sender_name="Даниил",
            sender_phone="89990000006",
        ),
    )

    assert action.kind == "send"
    text = "\n".join(action.messages).lower()
    assert "итог заказа" in text
    assert "самовывоз" in text
    assert "получател" not in text
    assert "способ оплаты" not in text
