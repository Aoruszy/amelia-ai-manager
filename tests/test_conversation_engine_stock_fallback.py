import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.llm_client import LLMError


class FailingLLM:
    async def generate(self, prompt: str) -> str:
        raise LLMError("quota")


@pytest.mark.asyncio
async def test_engine_stock_unavailable_fallback_when_llm_fails():
    engine = ConversationEngine(FailingLLM())

    action = await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: Есть пионы?"],
        stage="new_lead",
        stock_context="По наличию на сегодня релевантно:\n- пионы — нет",
    )

    assert action.kind == "send"
    assert "пионы" in action.messages[0].lower()
    assert "нет" in action.messages[0].lower() or "законч" in action.messages[0].lower()
    assert "бюджет" in action.messages[0].lower()
