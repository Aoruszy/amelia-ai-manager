import pytest

from amelia_manager.conversation_engine import ConversationAction, ConversationEngine
from amelia_manager.risk import RiskLevel


class FakeLLM:
    async def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        return "Да, конечно. Букет нужен на сегодня?"


@pytest.mark.asyncio
async def test_engine_sends_safe_low_risk_reply():
    llm = FakeLLM()
    engine = ConversationEngine(llm)

    action = await engine.handle_messages(
        client_summary="Новый клиент",
        recent_messages=["Здравствуйте, нужен букет девушке"],
        stage="new_lead",
    )

    assert action.kind == "send"
    assert action.messages == ["Да, конечно. Букет нужен на сегодня?"]
    assert action.risk_level == RiskLevel.LOW
    assert "Amelia Flowers" in llm.last_prompt


@pytest.mark.asyncio
async def test_engine_hands_off_high_risk_without_calling_llm():
    class ShouldNotCallLLM:
        async def generate(self, prompt: str) -> str:
            raise AssertionError("LLM should not be called for high risk")

    engine = ConversationEngine(ShouldNotCallLLM())

    action = await engine.handle_messages(
        client_summary="Клиент недоволен",
        recent_messages=["Мне привезли не то, хочу возврат"],
        stage="order_issue",
    )

    assert action.kind == "human_takeover"
    assert action.risk_level == RiskLevel.HIGH
    assert "передам" in action.messages[0].lower()


@pytest.mark.asyncio
async def test_sensitive_occasion_uses_calm_reply_without_emoji():
    action = await ConversationEngine(FakeLLM()).handle_messages(
        client_summary="Клиент",
        recent_messages=["Клиент: Нужен венок на похороны, завтра к 10:00"],
        stage="new",
    )

    text = action.messages[0].lower()
    assert action.kind == "send"
    assert action.risk_level == RiskLevel.MEDIUM
    assert "подскажите" in text
    assert "🌸" not in text
    assert "ярк" not in text
    assert "нежн" not in text


@pytest.mark.asyncio
async def test_guarantee_request_gets_cautious_reply_without_promise():
    action = await ConversationEngine(FakeLLM()).handle_messages(
        client_summary="Клиент",
        recent_messages=["Клиент: Белые розы точно будут? Гарантируете?"],
        stage="new",
    )

    text = action.messages[0].lower()
    assert action.kind == "send"
    assert action.risk_level == RiskLevel.MEDIUM
    assert "уточ" in text
    assert "гарантир" not in text
    assert "точно будут" not in text


@pytest.mark.asyncio
async def test_engine_hands_off_unsafe_llm_reply():
    class UnsafeLLM:
        async def generate(self, prompt: str) -> str:
            return "Я AI-бот, точно есть эти розы"

    engine = ConversationEngine(UnsafeLLM())

    action = await engine.handle_messages(
        client_summary="Новый клиент",
        recent_messages=["Есть розы?"],
        stage="bouquet_selection",
    )

    assert action.kind == "human_review"
    assert action.safety_reasons
