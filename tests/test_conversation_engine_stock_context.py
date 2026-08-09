import pytest

from amelia_manager.conversation_engine import ConversationEngine


class CapturingLLM:
    def __init__(self):
        self.prompt = ""

    async def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return "Сегодня по наличию есть голубая гортензия, можно собрать сине-белый букет."


@pytest.mark.asyncio
async def test_engine_passes_stock_context_to_prompt():
    llm = CapturingLLM()
    engine = ConversationEngine(llm)

    action = await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: хочу сине-белый букет с гортензией до 5000"],
        stage="new_lead",
        stock_context="По наличию на сегодня релевантно:\n- гортензия голубая — 8",
    )

    assert action.kind == "send"
    assert "гортензия голубая — 8" in llm.prompt
