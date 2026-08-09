import pytest

from amelia_manager.conversation_engine import ConversationEngine


class FakeLLM:
    async def generate(self, prompt: str) -> str:
        return "Отлично, данные вижу. Подскажите, пожалуйста, это доставка или самовывоз?"


@pytest.mark.asyncio
async def test_engine_does_not_handoff_when_history_contains_please_and_address():
    engine = ConversationEngine(FakeLLM())

    action = await engine.handle_messages(
        client_summary="Клиент оформляет букет",
        recent_messages=[
            "Менеджер: Напишите, пожалуйста, ваши имя и телефон, а также имя и телефон получателя.",
            "Клиент: Гайдара 173, Даниил 89990000007, получатель Ольга 89990000008",
        ],
        stage="new_lead",
    )

    assert action.kind == "send"
    assert "ответственному менеджеру" not in action.messages[0].lower()
