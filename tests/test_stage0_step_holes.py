from datetime import date

import pytest

from amelia_manager.company_profile import load_company_profile
from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.order_card import OrderCard, merge_order_state
from amelia_manager.order_policy import get_next_step
from amelia_manager.order_state import extract_order_state
from amelia_manager.safety import check_reply_safety
from amelia_manager.stock import BudgetOption, StockItem, StockStatus, build_stock_context, select_budget_options


def test_deferred_date_answers_do_not_write_placeholder_to_card():
    for answer in ("не важно", "когда получится", "в ближайшие дни", "на ваше усмотрение"):
        state = extract_order_state([f"Клиент: {answer}"], today=date(2026, 8, 19))
        assert state.delivery_date is None, answer


def test_non_answers_do_not_close_date_step():
    for answer in ("не знаю", "а что есть?", "подешевле"):
        state = extract_order_state([f"Клиент: {answer}"], today=date(2026, 8, 19))
        assert state.delivery_date is None, answer


def test_deferred_time_answers_do_not_write_placeholder_to_card():
    for answer in ("в любое", "когда удобно", "когда вам удобно", "побыстрее", "не принципиально"):
        state = extract_order_state([f"Клиент: {answer}"], today=date(2026, 8, 19))
        assert state.delivery_time is None, answer


def test_deferred_date_and_time_confirmations_use_manager_suggestion():
    date_state = extract_order_state(
        ["Менеджер: Могу записать на завтра — подойдёт?", "Клиент: да"],
        today=date(2026, 8, 19),
    )
    time_state = extract_order_state(["Менеджер: Давайте к 14:00, удобно?", "Клиент: да"], today=date(2026, 8, 19))

    assert date_state.delivery_date == "2026-08-20"
    assert time_state.delivery_time == "14:00"


def test_no_deferred_placeholder_is_written_to_any_order_card_field():
    state = extract_order_state(["Клиент: не важно, когда удобно, как удобнее"], today=date(2026, 8, 19))
    card = merge_order_state(OrderCard(), state)

    assert "по согласованию" not in str(card.to_dict())


def test_deferred_format_answers_do_not_close_fulfillment_step():
    for answer in ("как удобнее", "всё равно", "как вам проще"):
        state = extract_order_state([f"Клиент: {answer}"], today=date(2026, 8, 19))
        assert state.fulfillment_type is None, answer


@pytest.mark.asyncio
async def test_deferred_format_answer_offers_default_choice_without_filling_field():
    class NoLLM:
        async def generate(self, prompt: str, **kwargs):
            raise AssertionError("deferred fulfillment choice should be deterministic")

    action = await ConversationEngine(NoLLM()).handle_messages(
        client_summary="",
        recent_messages=["Клиент: как удобнее"],
        stage="new",
        order_card=OrderCard(budget=6000, colors=["розы"]),
    )

    assert action.kind == "send"
    assert action.next_step == "ask_when_where"
    assert "Самовывоз" in action.messages[0]
    assert "Сергеева, 61" in action.messages[0]
    assert "доставка" in action.messages[0].lower()
    assert extract_order_state(["Клиент: как удобнее"], today=date(2026, 8, 19)).fulfillment_type is None


def test_later_explicit_delivery_closes_fulfillment_after_deferred_choice():
    state = extract_order_state(["Клиент: как удобнее", "Клиент: давайте доставку"], today=date(2026, 8, 19))

    assert state.fulfillment_type == "delivery"
    assert get_next_step(state).code != "ask_fulfillment_type"


def test_order_after_deferred_then_explicit_fulfillment_becomes_admin_ready():
    card = OrderCard(
        budget=7000,
        colors=["розовый"],
        fulfillment_type=extract_order_state(["Клиент: как удобнее", "Клиент: давайте доставку"]).fulfillment_type,
        delivery_date="tomorrow",
        delivery_time="12:00",
        address="ул. Тестовая, 1",
        sender_name="Даниил",
        sender_phone="89990000002",
        recipient_name="Анна",
        recipient_phone="89990000003",
        payment_method="transfer",
    )

    assert card.is_ready_for_admin_request() is True


def test_fulfillment_type_accepts_only_pickup_delivery_or_none():
    for value in ("pickup", "delivery", None):
        assert OrderCard(fulfillment_type=value).fulfillment_type == value
    assert OrderCard(fulfillment_type="по согласованию").is_ready_for_admin_request() is False


def test_non_answers_do_not_close_time_or_format_steps():
    for answer in ("не знаю", "а что есть?", "подешевле"):
        state = extract_order_state([f"Клиент: {answer}"], today=date(2026, 8, 19))
        assert state.delivery_time is None, answer
        assert state.fulfillment_type is None, answer


def _catalog_context(*, sensitive=False):
    return build_stock_context(
        items=_catalog_items(),
        colors=[],
        desired_text="Клиент: не знаю бюджет",
        stock_date=date(2026, 8, 19),
        today=date(2026, 8, 19),
        composition_units=load_company_profile().composition_units,
        sensitive_occasion=sensitive,
        sensitive_forbidden_words=load_company_profile().sensitive_occasion_forbidden_words,
    )


def _catalog_options(*, sensitive=False, text="не знаю бюджет"):
    profile = load_company_profile()
    return select_budget_options(
        _catalog_items(),
        desired_text=text,
        composition_units=profile.composition_units,
        sensitive_occasion=sensitive,
        sensitive_forbidden_words=profile.sensitive_occasion_forbidden_words,
    )


async def _no_llm_reply(prompt: str, **kwargs):
    raise AssertionError("budget unknown with catalog options should be deterministic")


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
        budget_options=_catalog_options(),
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
        budget_options=_catalog_options(sensitive=True),
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


def test_polite_questions_are_not_budget_unknown_answers():
    for text in ("подскажите, а пионы есть?", "подскажите адрес", "подскажите пожалуйста часы работы"):
        assert select_budget_options(_catalog_items(), desired_text=text, composition_units=load_company_profile().composition_units).items == []


def test_previous_bot_budget_question_does_not_turn_stock_context_into_budget_options():
    context = build_stock_context(
        items=_catalog_items(),
        colors=[],
        desired_text="Менеджер: Подскажите, на какой бюджет ориентируемся?\nКлиент: подскажите, а пионы есть?",
        latest_client_text="подскажите, а пионы есть?",
        stock_date=date(2026, 8, 19),
        today=date(2026, 8, 19),
        composition_units=load_company_profile().composition_units,
    )

    assert context.startswith("По наличию на сегодня релевантно:")
    assert "пионы" in context
    assert "Варианты композиций" not in context


def test_budget_unknown_positive_triggers_budget_options():
    for text in ("не знаю", "затрудняюсь"):
        options = select_budget_options(_catalog_items(), desired_text=text, composition_units=load_company_profile().composition_units)
        assert [item.price for item in options.items] == [4200, 5500, 9000]


def test_budget_options_reply_uses_object_not_stock_context_string_format():
    class NoLLM:
        async def generate(self, prompt: str, **kwargs):
            raise AssertionError("budget options should be deterministic")

    options = [
        BudgetOption(name="малый букет", price=4200, unit="букет"),
        BudgetOption(name="средний букет", price=5500, unit="букет"),
        BudgetOption(name="премиум букет", price=9000, unit="букет"),
    ]

    async def run():
        return await ConversationEngine(NoLLM()).handle_messages(
            client_summary="",
            recent_messages=["Клиент: не знаю"],
            stage="new",
            stock_context="CATALOG FORMAT CHANGED; prices unavailable in text",
            order_card=OrderCard(),
            budget_options=options,
        )

    import asyncio
    action = asyncio.run(run())
    assert "малый букет — 4200 ₽" in action.messages[0]


def _catalog_items():
    return [
        StockItem("букет нежный пастельный", StockStatus.AVAILABLE, "3", 3, 4200, "букет"),
        StockItem("букет яркий микс", StockStatus.AVAILABLE, "5", 5, 5500, "букет"),
        StockItem("корзина с цветами", StockStatus.AVAILABLE, "2", 2, 7500, "композиция"),
        StockItem("премиум яркий букет", StockStatus.AVAILABLE, "1", 1, 9000, "букет"),
        StockItem("пионы розовые", StockStatus.AVAILABLE, "12", 12, 4500, "шт"),
        StockItem("розы", StockStatus.AVAILABLE, "20", 20, 250, "шт"),
        StockItem("нулевой букет", StockStatus.UNAVAILABLE, "нет", 0, 3000, "букет"),
    ]
