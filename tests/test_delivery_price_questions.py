import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.delivery_questions import is_city_delivery_price_question, is_delivery_price_question
from amelia_manager.risk import RiskCategory, RiskLevel, assess_risk


class StaticLLM:
    async def generate(self, prompt: str, **kwargs) -> str:
        return "Поняла. Подскажите, пожалуйста, недостающие детали заказа?"


def test_delivery_price_detector_distinguishes_city_from_out_of_area_cases():
    assert is_delivery_price_question("Сколько стоит доставка по городу?") is True
    assert is_city_delivery_price_question("Сколько стоит доставка по городу?") is True
    assert is_city_delivery_price_question("Сколько стоит доставка?") is True

    for text in (
        "Сколько стоит доставка за город?",
        "Сколько стоит доставка в Светлогорск?",
        "Доставка ночью сколько стоит?",
    ):
        assert is_delivery_price_question(text) is True
        assert is_city_delivery_price_question(text) is False


def test_out_of_area_delivery_price_questions_are_medium_risk():
    for text in (
        "Сколько стоит доставка за город?",
        "Сколько стоит доставка в Светлогорск?",
        "Доставка ночью сколько стоит?",
    ):
        risk = assess_risk(text)
        assert risk.level == RiskLevel.MEDIUM, text
        assert risk.category == RiskCategory.OUT_OF_AREA_DELIVERY, text


@pytest.mark.asyncio
async def test_out_of_area_delivery_price_questions_do_not_quote_city_price():
    engine = ConversationEngine(StaticLLM())
    for question in (
        "Сколько стоит доставка за город?",
        "Сколько стоит доставка в Светлогорск?",
        "Доставка ночью сколько стоит?",
    ):
        action = await engine.handle_messages(
            client_summary="Eval клиент",
            recent_messages=[f"Клиент: {question}"],
            stage="eval",
            stock_context="",
        )
        text = "\n".join(action.messages)
        assert action.risk_level == RiskLevel.MEDIUM, question
        assert "400" not in text, question
        assert "уточню у менеджера" in text.lower(), question
