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


def test_deferred_choice_counts_as_an_answer_about_preferences():
    """«На ваш выбор» — ответ. Без этого шаг про пожелания не закрывался и повторялся."""
    for answer in ("что нибудь на ваш выбор", "на ваше усмотрение", "доверяю вам", "сами выберите", "на ваш вкус"):
        state = extract_order_state([f"Клиент: {answer}"], today=date(2026, 8, 19))
        assert state.colors == ["без особых пожеланий"], answer


def test_ordinary_answers_do_not_become_a_deferred_choice():
    """Негативный случай: обычный ответ или отсутствие ответа пожеланием не считается."""
    assert extract_order_state(["Клиент: белые розы"], today=date(2026, 8, 19)).colors == ["белый", "розы"]
    for answer in ("не знаю", "а что есть?", "подешевле", "сколько стоит?"):
        assert extract_order_state([f"Клиент: {answer}"], today=date(2026, 8, 19)).colors == [], answer


def test_deferred_choice_does_not_override_a_real_preference():
    state = extract_order_state(
        ["Клиент: белые розы, остальное на ваш выбор"], today=date(2026, 8, 19)
    )

    assert "без особых пожеланий" not in state.colors
    assert state.colors == ["белый", "розы"]


def test_grouped_contact_answer_assigns_roles_by_nearby_words_not_question_text():
    forward = extract_order_state(
        [
            "Менеджер: Подскажите ваше имя и телефон, и имя с телефоном получателя.",
            "Клиент: Я Анна 89990000001, получатель Мария 89990000002",
        ]
    )
    reverse = extract_order_state(
        [
            "Менеджер: Подскажите ваше имя и телефон, и имя с телефоном получателя.",
            "Клиент: получатель Мария 89990000002, я Анна 89990000001",
        ]
    )

    for state in (forward, reverse):
        assert state.sender_name == "Анна"
        assert state.sender_phone == "89990000001"
        assert state.recipient_name == "Мария"
        assert state.recipient_phone == "89990000002"


def test_single_contact_in_grouped_question_goes_to_sender_and_does_not_invent_recipient():
    state = extract_order_state(
        [
            "Менеджер: Подскажите ваше имя и телефон, и имя с телефоном получателя.",
            "Клиент: Я Анна 89990000001",
        ]
    )

    assert state.sender_name == "Анна"
    assert state.sender_phone == "89990000001"
    assert state.recipient_name is None
    assert state.recipient_phone is None


def _option_dialog(answer: str) -> list[str]:
    return [
        "Менеджер: Могу показать три варианта: букет нежный пастельный — 4200 ₽, букет яркий микс — 5500 ₽, премиум яркий букет — 9000 ₽. Что ближе?",
        f"Клиент: {answer}",
    ]


def test_catalog_option_choice_by_ordinal_level_name_or_price_fills_budget_and_preferences():
    cases = [
        ("давайте второй", 5500, "букет яркий микс"),
        ("средний", 5500, "букет яркий микс"),
        ("букет яркий микс", 5500, "букет яркий микс"),
        ("5500", 5500, "букет яркий микс"),
        ("подороже", 9000, "премиум яркий букет"),
        ("дешевле", 4200, "букет нежный пастельный"),
    ]

    for answer, budget, preference in cases:
        state = extract_order_state(_option_dialog(answer), today=date(2026, 8, 19))
        assert state.budget == budget, answer
        assert state.colors == [preference], answer


def test_catalog_option_choice_closes_preferences_step():
    from amelia_manager.order_policy import get_next_step

    state = extract_order_state(
        [
            *_option_dialog("средний"),
            "Клиент: доставка завтра к 14:00 на Ленина 5",
        ],
        today=date(2026, 8, 19),
    )

    assert state.budget == 5500
    assert state.colors == ["букет яркий микс"]
    assert get_next_step(state).code == "ask_when_where"
    assert get_next_step(state).code != "ask_bouquet_preferences"


def test_catalog_option_negative_answers_do_not_fill_budget_or_preferences():
    for answer in ("а есть что-то другое?", "ни один не подходит", "не эти", "пока подумаю"):
        state = extract_order_state(_option_dialog(answer), today=date(2026, 8, 19))
        assert state.budget is None, answer
        assert state.colors == [], answer


def test_catalog_option_numeric_choice_does_not_capture_dates_or_quantities():
    cases = [
        ("давайте 1 сентября", "2026-09-01"),
        ("заберу 3 числа", None),
        ("нужно 2 букета", None),
    ]

    for answer, expected_date in cases:
        state = extract_order_state(_option_dialog(answer), today=date(2026, 8, 19))
        assert state.budget is None, answer
        assert state.colors == [], answer
        assert state.delivery_date == expected_date, answer


def test_catalog_option_numeric_choice_accepts_only_explicit_option_number():
    for answer in ("2", "2)", "вариант 2"):
        state = extract_order_state(_option_dialog(answer), today=date(2026, 8, 19))
        assert state.budget == 5500, answer
        assert state.colors == ["букет яркий микс"], answer


def test_catalog_option_choice_preserves_later_client_preferences_and_forbidden_flowers():
    with_choice = extract_order_state(
        [
            *_option_dialog("второй"),
            "Клиент: только белые, без лилий, завтра к 15 на Ленина 5",
        ],
        today=date(2026, 8, 19),
    )
    without_choice = extract_order_state(
        ["Клиент: только белые, без лилий, завтра к 15 на Ленина 5"],
        today=date(2026, 8, 19),
    )

    assert "букет яркий микс" in with_choice.colors
    assert "белый" in with_choice.colors
    assert "лилии" in with_choice.forbidden_flowers
    assert without_choice.colors == ["белый"]
    assert "лилии" in without_choice.forbidden_flowers
