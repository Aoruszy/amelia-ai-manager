from datetime import date

from amelia_manager.company_profile import load_company_profile
from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.order_card import OrderCard
from amelia_manager.order_state import extract_order_state
from amelia_manager.safety import check_reply_safety
from amelia_manager.stock import StockItem, StockStatus, build_stock_context


def test_deferred_date_answers_close_date_step_with_placeholder():
    for answer in ("не важно", "когда получится", "в ближайшие дни", "на ваше усмотрение"):
        state = extract_order_state([f"Клиент: {answer}"], today=date(2026, 8, 19))
        assert state.delivery_date == "по согласованию", answer


def test_non_answers_do_not_close_date_step():
    for answer in ("не знаю", "а что есть?", "подешевле"):
        state = extract_order_state([f"Клиент: {answer}"], today=date(2026, 8, 19))
        assert state.delivery_date is None, answer


def test_deferred_time_answers_close_time_step_with_placeholder():
    for answer in ("в любое", "когда удобно", "когда вам удобно", "побыстрее", "не принципиально"):
        state = extract_order_state([f"Клиент: {answer}"], today=date(2026, 8, 19))
        assert state.delivery_time == "по согласованию", answer


def test_deferred_format_answers_close_fulfillment_step_with_placeholder():
    for answer in ("как удобнее", "всё равно", "как вам проще"):
        state = extract_order_state([f"Клиент: {answer}"], today=date(2026, 8, 19))
        assert state.fulfillment_type == "по согласованию", answer


def test_non_answers_do_not_close_time_or_format_steps():
    for answer in ("не знаю", "а что есть?", "подешевле"):
        state = extract_order_state([f"Клиент: {answer}"], today=date(2026, 8, 19))
        assert state.delivery_time is None, answer
        assert state.fulfillment_type is None, answer


def _catalog_context(*, sensitive=False):
    items = [
        StockItem("букет нежный пастельный", StockStatus.AVAILABLE, "3", 3, 4200, "букет"),
        StockItem("букет яркий микс", StockStatus.AVAILABLE, "5", 5, 5500, "букет"),
        StockItem("корзина с цветами", StockStatus.AVAILABLE, "2", 2, 7500, "композиция"),
        StockItem("премиум яркий букет", StockStatus.AVAILABLE, "1", 1, 9000, "букет"),
        StockItem("розы", StockStatus.AVAILABLE, "20", 20, 250, "шт"),
        StockItem("нулевой букет", StockStatus.UNAVAILABLE, "нет", 0, 3000, "букет"),
    ]
    return build_stock_context(
        items=items,
        colors=[],
        desired_text="Клиент: не знаю бюджет",
        stock_date=date(2026, 8, 19),
        today=date(2026, 8, 19),
        composition_units=load_company_profile().composition_units,
        sensitive_occasion=sensitive,
        sensitive_forbidden_words=load_company_profile().sensitive_occasion_forbidden_words,
    )


async def _no_llm_reply(prompt: str, **kwargs):
    raise AssertionError("budget unknown with catalog options should be deterministic")


import pytest


@pytest.mark.asyncio
async def test_budget_unknown_gets_three_catalog_compositions_in_ascending_price():
    class NoLLM:
        generate = staticmethod(_no_llm_reply)

    action = await ConversationEngine(NoLLM()).handle_messages(
        client_summary="",
        recent_messages=["Клиент: не знаю бюджет"],
        stage="new",
        stock_context=_catalog_context(),
        order_card=OrderCard(),
    )

    text = action.messages[0]
    assert action.kind == "send"
    assert "букет нежный пастельный — 4200 ₽" in text
    assert "букет яркий микс — 5500 ₽" in text
    assert "премиум яркий букет — 9000 ₽" in text
    assert text.index("4200") < text.index("5500") < text.index("9000")
    assert "розы" not in text
    assert "нулевой" not in text
    assert text.count("?") == 1
    assert check_reply_safety(text, stock_context=_catalog_context()).is_safe


@pytest.mark.asyncio
async def test_budget_unknown_sensitive_filters_forbidden_names_and_uses_levels_when_too_few_left():
    class NoLLM:
        generate = staticmethod(_no_llm_reply)

    action = await ConversationEngine(NoLLM()).handle_messages(
        client_summary="",
        recent_messages=["Клиент: не знаю бюджет"],
        stage="new",
        stock_context=_catalog_context(sensitive=True),
        order_card=OrderCard(custom_fields={"occasion_sensitive": True}),
    )

    text = action.messages[0].lower()
    assert action.kind == "send"
    assert "нежн" not in text
    assert "ярк" not in text
    assert "4200" in text and "5500" in text and "9000" in text
    assert "🌸" not in text


@pytest.mark.asyncio
async def test_budget_unknown_empty_catalog_falls_back_to_budget_question():
    class NoLLM:
        generate = staticmethod(_no_llm_reply)

    action = await ConversationEngine(NoLLM()).handle_messages(
        client_summary="",
        recent_messages=["Клиент: не знаю бюджет"],
        stage="new",
        stock_context="По наличию на сегодня нет явно подходящих позиций под запрос.",
        order_card=OrderCard(),
    )

    assert action.kind == "send"
    assert "бюджет" in action.messages[0].lower()
    assert "—" not in action.messages[0]
