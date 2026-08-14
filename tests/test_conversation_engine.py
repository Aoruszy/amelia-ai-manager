import pytest

from amelia_manager.conversation_engine import ConversationAction, ConversationEngine
from amelia_manager.order_card import OrderCard
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
    assert action.order_patch == {"custom_fields": {"occasion_sensitive": True}}


@pytest.mark.asyncio
async def test_sensitive_occasion_stays_sticky_across_later_turns():
    class SensitiveAwareLLM:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def generate(self, prompt: str, **kwargs) -> str:
            self.prompts.append(prompt)
            assert "occasion_sensitive" in prompt
            assert "без эмодзи" in prompt
            assert "не используй слова" in prompt.lower()
            assert "яркий" in prompt.lower()
            if len(self.prompts) == 1:
                return '{"intent":"order","emotion":"grief","reply":"Соберу очень нежный и яркий букет 🌸 На какое время подготовить?","case_patch":{},"next_step":"ask_pickup_time","needs_human":false,"confidence":0.9}'
            assert "запрещённые слова для чувствительного повода" in prompt
            return '{"intent":"order","emotion":"grief","reply":"Поняла. Сделаю сдержанно и по делу. На какое время подготовить?","case_patch":{},"next_step":"ask_pickup_time","needs_human":false,"confidence":0.9}'

    card = OrderCard(
        occasion="похороны",
        budget=5000,
        colors=["белый"],
        fulfillment_type="pickup",
        delivery_date="завтра",
        custom_fields={"occasion_sensitive": True},
    )

    llm = SensitiveAwareLLM()
    action = await ConversationEngine(llm).handle_messages(
        client_summary="Клиент заказал венок на похороны",
        recent_messages=["Клиент: Хорошо, давайте белый"],
        stage="pickup",
        order_card=card,
    )

    text = action.messages[0].lower()
    assert action.kind == "send"
    assert len(llm.prompts) == 2
    assert "🌸" not in text
    assert "ярк" not in text
    assert "нежн" not in text
    assert "очень и букет" not in text


@pytest.mark.asyncio
async def test_sensitive_occasion_context_from_history_protects_even_without_order_card():
    class UnsafeSensitiveLLM:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def generate(self, prompt: str, **kwargs) -> str:
            self.prompts.append(prompt)
            assert "occasion_sensitive" in prompt
            if len(self.prompts) == 1:
                return '{"intent":"order","emotion":"grief","reply":"Соберу очень нежный и яркий букет 🌸","case_patch":{},"next_step":"ask_bouquet_preferences","needs_human":false,"confidence":0.9}'
            assert "запрещённые слова для чувствительного повода" in prompt
            return '{"intent":"order","emotion":"grief","reply":"Поняла. Сделаю сдержанно и по делу.","case_patch":{},"next_step":"ask_bouquet_preferences","needs_human":false,"confidence":0.9}'

    llm = UnsafeSensitiveLLM()
    action = await ConversationEngine(llm).handle_messages(
        client_summary="",
        recent_messages=[
            "Клиент: Нужен венок на похороны",
            "Менеджер: Понимаю. Подскажите бюджет и формат.",
            "Клиент: Давайте белый",
        ],
        stage="new",
        order_card=None,
    )

    text = action.messages[0].lower()
    assert action.kind == "send"
    assert len(llm.prompts) == 2
    assert "🌸" not in text
    assert "ярк" not in text
    assert "нежн" not in text
    assert "очень и букет" not in text


@pytest.mark.asyncio
async def test_pickup_time_reply_keeps_pickup_address_when_model_omits_it():
    class PickupTimeLLM:
        async def generate(self, prompt: str, **kwargs) -> str:
            return '{"intent":"order","emotion":"neutral","reply":"Записала: до 5000 ₽, самовывоз сегодня. К какому времени удобно забрать?","case_patch":{},"next_step":"ask_pickup_time","needs_human":false,"confidence":0.9}'

    action = await ConversationEngine(PickupTimeLLM()).handle_messages(
        client_summary="Клиент выбрал самовывоз сегодня до 5000 ₽",
        recent_messages=["Клиент: до 5000, самовывоз сегодня"],
        stage="pickup",
        order_card=OrderCard(budget=5000, fulfillment_type="pickup", delivery_date="сегодня"),
    )

    assert action.kind == "send"
    assert "Сергеева, 61" in action.messages[0]


@pytest.mark.asyncio
async def test_pickup_time_reply_keeps_pickup_address_even_without_card_patch():
    class PickupTimeLLM:
        async def generate(self, prompt: str, **kwargs) -> str:
            return '{"intent":"order","emotion":"neutral","reply":"Записала: самовывоз сегодня. К какому времени удобно забрать?","case_patch":{},"next_step":"ask_pickup_time","needs_human":false,"confidence":0.9}'

    action = await ConversationEngine(PickupTimeLLM()).handle_messages(
        client_summary="Клиент выбрал самовывоз сегодня",
        recent_messages=["Клиент: самовывоз сегодня"],
        stage="pickup",
        order_card=None,
    )

    assert action.kind == "send"
    assert "Сергеева, 61" in action.messages[0]


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
        recent_messages=["Нужен букет"],
        stage="bouquet_selection",
    )

    assert action.kind == "human_review"
    assert action.safety_reasons
