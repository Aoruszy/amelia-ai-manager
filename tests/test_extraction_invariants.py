"""Regression invariants for deterministic order-state extraction.

Dialogue eval checks reply text and next_step, but it does not assert raw
OrderState field values. Budget/address/phone confusion must be locked at the
extract_order_state layer directly.
"""

from amelia_manager.order_state import extract_order_state


def test_budget_raised_later_in_dialog_wins():
    """Клиент поднимает бюджет по ходу разговора — побеждает последнее названное."""
    state = extract_order_state([
        "Менеджер: Подскажите бюджет",
        "Клиент: 5000",
        "Менеджер: Хорошо, а какие оттенки нравятся?",
        "Клиент: давайте лучше до 7000",
    ])

    assert state.budget == 7000


def test_budget_raised_with_explicit_word_wins():
    state = extract_order_state([
        "Менеджер: Подскажите бюджет",
        "Клиент: 5000",
        "Менеджер: Хорошо",
        "Клиент: бюджет 8000",
    ])

    assert state.budget == 8000


def test_house_number_in_later_address_does_not_replace_budget():
    state = extract_order_state([
        "Клиент: до 5000",
        "Менеджер: Куда доставить?",
        "Клиент: доставка на Ленина 1205",
    ])

    assert state.budget == 5000


def test_apartment_number_does_not_replace_budget():
    state = extract_order_state([
        "Клиент: до 5000",
        "Менеджер: Куда доставить?",
        "Клиент: улица Гагарина 1140, кв 12",
    ])

    assert state.budget == 5000


def test_implicit_budget_in_first_message_is_extracted():
    """Клиент пишет сумму числом без слова-маркера — так пишут чаще всего."""
    for message in (
        "Клиент: 5000 нежный",
        "Клиент: 5000 нежный самовывоз сегодня",
        "Клиент: Нужен букет, 5000",
        "Клиент: 5000",
    ):
        assert extract_order_state([message]).budget == 5000, message


def test_dates_order_numbers_and_phones_are_not_budget():
    cases = {
        "Клиент: Нужен букет на 15.03.2026": None,
        "Клиент: Давайте на 20.12.2026, самовывоз": None,
        "Клиент: мой заказ номер 12345": None,
        "Клиент: Даниил 89990000002": None,
        "Клиент: Доставка на ул. Гайдара 173, Даниил 89990000002": None,
    }
    for message, expected in cases.items():
        assert extract_order_state([message]).budget == expected, message


def test_explicit_budget_survives_neighbouring_numbers():
    assert extract_order_state(["Клиент: бюджет 5000, доставка 15.03.2026"]).budget == 5000
    assert extract_order_state(["Клиент: бюджет до 5 тысяч, дом 3456"]).budget == 5000
    assert extract_order_state(["Клиент: 5к"]).budget == 5000
