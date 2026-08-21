import pytest

from amelia_manager.conversation_engine import ConversationEngine


class CapturingLLM:
    def __init__(self):
        self.prompt = ""

    async def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return "Записала на сегодня к 18:00 🙂 Это доставка или самовывоз?"


@pytest.mark.asyncio
async def test_engine_passes_next_step_instruction_to_prompt():
    llm = CapturingLLM()
    engine = ConversationEngine(llm)

    action = await engine.handle_messages(
        client_summary="Клиент хочет букет девушке",
        recent_messages=[
            "Клиент: Хочу подарить цветы своей девушке",
            "Клиент: Любимый цвет синий и белый, бюджет 7000",
            "Клиент: На сегодня в 18:00",
        ],
        stage="new_lead",
    )

    assert action.kind == "send"
    assert "Следующий обязательный шаг" in llm.prompt
    assert "доставка" in llm.prompt
    assert "самовывоз" in llm.prompt
    assert "куда" in llm.prompt
