from amelia_manager.order_state import extract_order_state


def test_extracts_standalone_budget_when_client_replies_with_number():
    state = extract_order_state(
        [
            "Клиент: Хотел бы цветы купить",
            "Менеджер: С каким бюджетом сориентировать вас по букету?",
            "Клиент: 5000",
        ]
    )

    assert state.budget == 5000


def test_extracts_pickup_flow_fields_from_long_real_dialog():
    state = extract_order_state(
        [
            "Клиент: Хотел бы цветы купить",
            "Клиент: 5000",
            "Клиент: Самовывоз",
            "Клиент: Сегодня в 18:00",
            "Клиент: Даниил 89990000006",
            "Клиент: Какой нибудь красивый, не знаю",
            "Клиент: Сине белое можно",
            "Клиент: Открытку не нужно",
        ]
    )

    assert state.budget == 5000
    assert state.fulfillment_type == "pickup"
    assert state.delivery_date == "today"
    assert state.delivery_time == "18:00"
    assert state.sender_name == "Даниил"
    assert state.sender_phone == "89990000006"
    assert state.colors == ["синий", "белый"]
