import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.order_card import OrderCard


class CapturingLLM:
    def __init__(self):
        self.prompt = ""

    async def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return "Уточните способ оплаты, пожалуйста 🌸"


@pytest.mark.asyncio
async def test_engine_passes_compact_order_card_to_prompt_so_model_does_not_forget_known_time():
    llm = CapturingLLM()
    engine = ConversationEngine(llm)
    card = OrderCard(
        budget=5000,
        colors=["белый"],
        fulfillment_type="delivery",
        delivery_date="17 августа",
        delivery_time="17:00",
        address="Гайдара 173 кв 14",
        sender_name="Даниил",
        sender_phone="89990000003",
        recipient_name="Ольга",
        recipient_phone="89990000004",
    )

    await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: Даниил 89990000003"],
        stage="ordering",
        order_card=card,
    )

    assert "Текущая карточка заказа" in llm.prompt
    assert "Время: 17:00" in llm.prompt
    assert "Дата: 17 августа" in llm.prompt
    assert "Получатель: Ольга, 89990000004" in llm.prompt
    assert "Не переспрашивай поля" in llm.prompt
