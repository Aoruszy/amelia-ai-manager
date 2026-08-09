import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.llm_client import LLMError
from amelia_manager.risk import RiskLevel


class FailingLLM:
    async def generate(self, prompt: str) -> str:
        raise LLMError("quota")


@pytest.mark.asyncio
async def test_stale_complaint_in_history_does_not_make_new_normal_request_high_risk():
    action = await ConversationEngine(FailingLLM()).handle_messages(
        client_summary="",
        recent_messages=[
            "Клиент: Что за бред вы мне пишите !!",
            "Менеджер: Передам менеджеру, чтобы вам ответили корректно.",
            "Клиент: Здравствуйте",
            "Менеджер: Здравствуйте 🙂 Чем могу помочь?",
            "Клиент: Хочу цветы купить",
        ],
        stage="new_lead",
    )

    assert action.risk_level == RiskLevel.LOW
    assert action.kind == "send"
    assert "бюджет" in action.messages[0].lower()
    assert "передам" not in action.messages[0].lower()


@pytest.mark.asyncio
async def test_latest_complaint_still_goes_high_risk():
    action = await ConversationEngine(FailingLLM()).handle_messages(
        client_summary="",
        recent_messages=["Клиент: Хочу цветы купить", "Клиент: Что за бред вы мне пишите !!"],
        stage="new_lead",
    )

    assert action.risk_level == RiskLevel.HIGH
    assert action.kind == "human_takeover"
