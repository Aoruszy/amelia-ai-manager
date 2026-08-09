import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.risk import RiskLevel


class ShouldNotCallLLM:
    async def generate(self, prompt: str) -> str:
        raise AssertionError("medium risk cautious replies should not require an LLM call")


@pytest.mark.asyncio
async def test_discount_question_gets_cautious_answer_not_human_takeover():
    action = await ConversationEngine(ShouldNotCallLLM()).handle_messages(
        client_summary="Новый клиент",
        recent_messages=["Клиент: А скидки бывают?"],
        stage="new_lead",
    )

    assert action.kind == "send"
    assert action.risk_level == RiskLevel.MEDIUM
    assert "уточню" in action.messages[0].lower()
    assert "менеджер" in action.messages[0].lower()


@pytest.mark.asyncio
async def test_refund_complaint_still_goes_human_takeover():
    action = await ConversationEngine(ShouldNotCallLLM()).handle_messages(
        client_summary="Клиент недоволен",
        recent_messages=["Клиент: Мне привезли не то, хочу возврат"],
        stage="order_issue",
    )

    assert action.kind == "human_takeover"
    assert action.risk_level == RiskLevel.HIGH
