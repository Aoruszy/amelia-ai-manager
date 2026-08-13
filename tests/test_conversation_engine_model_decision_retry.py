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


class TruncatedThenJsonLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **kwargs) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if self.calls == 1:
            return '{"intent":"order","reply":"Записала: самовывоз завтра в 18:00","case_patch":{"date":"на завтра"'
        return '{"intent":"order","reply":"Подскажите, пожалуйста, ваше имя и телефон для связи по заказу?","case_patch":{},"next_step":"ask_sender_contacts","needs_human":false,"confidence":0.83}'


@pytest.mark.asyncio
async def test_truncated_model_decision_is_retried_and_not_sent_raw():
    llm = TruncatedThenJsonLLM()

    action = await ConversationEngine(llm).handle_messages(
        client_summary="Новый клиент",
        recent_messages=["Клиент: Самовывоз завтра в 18:00, нежный пастельный букет, бюджет 5000-7000"],
        stage="new_lead",
    )

    assert llm.calls == 2
    assert "корректный JSON" in llm.prompts[1]
    assert action.kind == "send"
    assert action.messages == ["Подскажите, пожалуйста, ваше имя и телефон для связи по заказу?"]
    assert not action.messages[0].startswith("{")
    assert "parse_failed" in action.safety_reasons
    assert action.safety_retry_succeeded is True


class AlwaysTruncatedLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, prompt: str, **kwargs) -> str:
        self.calls += 1
        return '{"intent":"order","reply":"сырой служебный JSON", "case_patch":{"budget":7000}'


@pytest.mark.asyncio
async def test_truncated_model_decision_twice_falls_back_without_raw_json():
    llm = AlwaysTruncatedLLM()

    action = await ConversationEngine(llm).handle_messages(
        client_summary="Новый клиент",
        recent_messages=["Клиент: Хочу букет 5000 нежный"],
        stage="new_lead",
    )

    assert llm.calls == 2
    assert action.kind == "send"
    assert action.messages
    assert not action.messages[0].startswith("{")
    assert '"case_patch"' not in action.messages[0]
    assert "parse_failed" in action.safety_reasons
    assert action.safety_retry_succeeded is False


class ValidJsonLLM:
    async def generate(self, prompt: str, **kwargs) -> str:
        return '{"intent":"order","reply":"Записала, подскажите бюджет.","case_patch":{},"next_step":"ask_budget","needs_human":false,"confidence":0.9}'


@pytest.mark.asyncio
async def test_valid_model_decision_behavior_is_unchanged():
    action = await ConversationEngine(ValidJsonLLM()).handle_messages(
        client_summary="Новый клиент",
        recent_messages=["Клиент: Хочу букет"],
        stage="new_lead",
    )

    assert action.kind == "send"
    assert action.messages == ["Записала, подскажите бюджет."]
    assert action.intent == "order"
    assert action.next_step == "ask_budget"
    assert action.confidence == 0.9
