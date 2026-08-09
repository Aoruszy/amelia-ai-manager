import pytest

from amelia_manager.conversation_engine import ConversationEngine


class RetryLLM:
    def __init__(self):
        self.prompts = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            return "Я AI, сейчас уточню у флориста и скоро пришлю фото."
        return "Поняла вас. Подскажите, пожалуйста, удобный способ оплаты?"


@pytest.mark.asyncio
async def test_engine_retries_once_when_safety_blocks_reply():
    llm = RetryLLM()
    engine = ConversationEngine(llm)

    action = await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: сине белое можно до 5000"],
        stage="new_lead",
    )

    assert action.kind == "send"
    assert action.messages == ["Поняла вас. Подскажите, пожалуйста, удобный способ оплаты?"]
    assert len(llm.prompts) == 2
    assert "нарушил правило безопасности" in llm.prompts[1]
