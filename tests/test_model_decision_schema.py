import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.model_decision import parse_model_decision


class JsonDecisionLLM:
    async def generate(self, prompt: str) -> str:
        return '{"intent":"appointment","reply":"Подскажите, пожалуйста, имя пациента.","case_patch":{"custom_fields":{"service":"чистка зубов"}},"next_step":"ask_patient_name","needs_human":false,"confidence":0.9}'


class HumanDecisionLLM:
    async def generate(self, prompt: str) -> str:
        return '{"intent":"complaint","reply":"Передам менеджеру, чтобы посмотрели детали.","needs_human":true,"confidence":0.8}'


def test_parse_model_decision_from_json_object():
    decision = parse_model_decision('{"reply":"Да, подскажу","needs_human":false,"case_patch":{"budget":5000}}')

    assert decision.reply == "Да, подскажу"
    assert decision.needs_human is False
    assert decision.case_patch == {"budget": 5000}


def test_parse_model_decision_returns_none_for_plain_text():
    assert parse_model_decision("Да, конечно") is None


@pytest.mark.asyncio
async def test_engine_uses_reply_from_structured_model_decision():
    action = await ConversationEngine(JsonDecisionLLM()).handle_messages(
        client_summary="",
        recent_messages=["Клиент: хочу записаться"],
        stage="new_lead",
    )

    assert action.kind == "send"
    assert action.messages == ["Подскажите, пожалуйста, имя пациента."]


@pytest.mark.asyncio
async def test_engine_routes_structured_needs_human_decision_to_review():
    action = await ConversationEngine(HumanDecisionLLM()).handle_messages(
        client_summary="",
        recent_messages=["Клиент: нестандартный вопрос"],
        stage="new_lead",
    )

    assert action.kind == "human_review"
    assert action.messages == ["Передам менеджеру, чтобы посмотрели детали."]
