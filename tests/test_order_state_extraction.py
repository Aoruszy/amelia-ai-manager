from datetime import date

from amelia_manager.order_state import extract_order_state


def test_extracts_order_state_from_real_dialog():
    state = extract_order_state(
        [
            "Клиент: Хочу подарить цветы своей девушке",
            "Менеджер: Какой любимый цвет и бюджет?",
            "Клиент: Любимый цвет синий и белый, бюджет 7000",
            "Менеджер: На какое число и доставка или самовывоз?",
            "Клиент: На сегодня в 18:00",
            "Менеджер: Это доставка или самовывоз?",
            "Клиент: Доставка на ул. Гайдара 173, Даниил 89990000007, получатель Ольга 89990000008",
        ],
        today=date(2026, 8, 9),
    )

    assert state.occasion == "девушке"
    assert state.budget == 7000
    assert state.colors == ["синий", "белый"]
    assert state.fulfillment_type == "delivery"
    assert state.delivery_date == "2026-08-09"
    assert state.delivery_time == "18:00"
    assert state.address == "ул. Гайдара 173"
    assert state.sender_name == "Даниил"
    assert state.sender_phone == "89990000007"
    assert state.recipient_name == "Ольга"
    assert state.recipient_phone == "89990000008"


def test_manager_stock_phrase_is_not_read_as_the_order_date():
    """«На сегодня гортензии нет» — про наличие, а не про дату заказа."""
    state = extract_order_state(
        [
            "Клиент: нужен букет из голубой гортензии, бюджет 7000",
            "Менеджер: На сегодня голубой гортензии нет. Вам доставка или самовывоз?",
            "Клиент: Хорошо, подберите. Цветы заберу сам",
        ],
        today=date(2026, 8, 16),
    )

    assert state.delivery_date is None


def test_manager_scheduling_phrase_still_supplies_the_date():
    """Негативный случай к предыдущему: из вопроса о сроке дату брать по-прежнему нужно."""
    asked = extract_order_state(
        [
            "Клиент: нужен букет",
            "Менеджер: Подскажите, к какому примерно времени сегодня планируете забрать букет?",
            "Клиент: к 18:00",
        ],
        today=date(2026, 8, 16),
    )
    confirmed = extract_order_state(
        [
            "Клиент: нужен букет",
            "Менеджер: Записала на завтра к 18:00 🌷 Как к вам обращаться?",
            "Клиент: Даниил",
        ],
        today=date(2026, 8, 16),
    )

    assert asked.delivery_date == "2026-08-16"
    assert confirmed.delivery_date == "2026-08-17"


def test_client_date_wins_over_anything_the_manager_said():
    state = extract_order_state(
        ["Менеджер: На сегодня гортензии нет", "Клиент: 20 августа в 19:00"],
        today=date(2026, 8, 16),
    )

    assert state.delivery_date == "2026-08-20"
    assert state.delivery_time == "19:00"


def test_client_can_change_the_date_within_the_dialog():
    later = extract_order_state(
        ["Клиент: давайте 20 августа", "Клиент: хотя нет, лучше завтра"], today=date(2026, 8, 16)
    )
    explicit = extract_order_state(
        ["Клиент: давайте завтра", "Клиент: хотя нет, 20 августа"], today=date(2026, 8, 16)
    )

    assert later.delivery_date == "2026-08-17"
    assert explicit.delivery_date == "2026-08-20"
