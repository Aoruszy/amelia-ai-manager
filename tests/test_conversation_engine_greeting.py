import pytest

from amelia_manager.conversation_engine import ConversationEngine


class ShouldNotCallLLM:
    async def generate(self, prompt: str) -> str:
        raise AssertionError("LLM should not be called for greeting-only messages")


@pytest.mark.asyncio
async def test_engine_answers_plain_greeting_without_delivery_question():
    engine = ConversationEngine(ShouldNotCallLLM())

    action = await engine.handle_messages(
        client_summary="Новый клиент",
        recent_messages=["Клиент: Здравствуйте"],
        stage="new_lead",
    )

    assert action.kind == "send"
    assert action.messages == ["Здравствуйте 🙂 Чем могу помочь?"]
    assert "доставка" not in action.messages[0].lower()
