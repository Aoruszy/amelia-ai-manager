import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.llm_client import LLMError


class UnsafeThenJsonLLM:
    def __init__(self):
        self.calls = 0

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        if self.calls == 1:
            return "Я бот и помогу оформить заказ."
        return '{"intent":"answer","reply":"Да, подскажу по букету.","needs_human":false}'


@pytest.mark.asyncio
async def test_safety_retry_parses_model_decision_json_before_sending():
    action = await ConversationEngine(UnsafeThenJsonLLM()).handle_messages(
        client_summary="Новый клиент",
        recent_messages=["Клиент: Хочу букет"],
        stage="new_lead",
    )

    assert action.kind == "send"
    assert action.messages == ["Да, подскажу по букету."]
    assert not action.messages[0].startswith("{")


class AlwaysFailsLLM:
    async def generate(self, prompt: str) -> str:
        raise LLMError("fail")
