import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.llm_client import LLMError
from amelia_manager.order_card import OrderCard


class FailingLLM:
    async def generate(self, prompt: str) -> str:
        raise LLMError("temporary provider error")


@pytest.mark.asyncio
async def test_engine_uses_deterministic_order_reply_when_llm_fails_on_typical_step():
    engine = ConversationEngine(FailingLLM())

    action = await engine.handle_messages(
        client_summary="Новый клиент",
        recent_messages=["Клиент: Бюджет 5000, девушке"],
        stage="new_lead",
        order_card=OrderCard(budget=5000, occasion="девушке"),
    )

    assert action.kind == "send"
    assert "оттен" in action.messages[0].lower() or "цвет" in action.messages[0].lower()
    assert "менеджер" not in action.messages[0].lower()


@pytest.mark.asyncio
async def test_engine_uses_budget_fallback_when_llm_fails_without_order_context():
    engine = ConversationEngine(FailingLLM())

    action = await engine.handle_messages(
        client_summary="Новый клиент",
        recent_messages=["Клиент: Нестандартный вопрос про букет"],
        stage="new_lead",
    )

    assert action.kind == "send"
    assert "бюджет" in action.messages[0].lower()
    assert "менеджер" not in action.messages[0].lower()
    assert "llm_error_fallback" in action.safety_reasons
