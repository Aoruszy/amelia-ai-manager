import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.delivery_questions import is_city_delivery_price_question, is_delivery_price_question
from amelia_manager.risk import RiskCategory, RiskLevel, assess_risk


class StaticLLM:
    async def generate(self, prompt: str, **kwargs) -> str:
        return "Поняла. Подскажите, пожалуйста, недостающие детали заказа?"


def test_delivery_price_detector_distinguishes_city_from_out_of_area_cases():
    for text in (
        "Сколько стоит доставка по городу?",
        "Сколько стоит доставка в городе?",
        "Сколько стоит доставка в пределах города?",
        "Сколько стоит доставка по Калининграду?",
        "Сколько стоит доставка?",
    ):
        assert is_delivery_price_question(text) is True
        assert is_city_delivery_price_question(text) is True, text
        risk = assess_risk(text)
        assert risk.level == RiskLevel.LOW, text

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
        "Сколько стоит доставка в область?",
        "Сколько стоит доставка в Светлогорск?",
        "Доставка ночью сколько стоит?",
        "Сколько стоит доставка после 22:00?",
    ):
        risk = assess_risk(text)
        assert risk.level == RiskLevel.MEDIUM, text
        assert risk.category == RiskCategory.OUT_OF_AREA_DELIVERY, text


def test_non_direction_words_after_prepositions_are_not_out_of_area():
    for text in (
        "Сколько стоит доставка в субботу?",
        "Сколько стоит доставка в понедельник?",
        "Сколько стоит доставка до вечера?",
        "Сколько стоит доставка в центр?",
        "Сколько стоит доставка до подъезда?",
        "Доставка платная? Хочу в офис",
    ):
        risk = assess_risk(text)
        assert risk.category != RiskCategory.OUT_OF_AREA_DELIVERY, text
        assert risk.level != RiskLevel.MEDIUM, text


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
