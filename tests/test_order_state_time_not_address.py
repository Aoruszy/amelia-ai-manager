from amelia_manager.order_state import extract_order_state


def test_delivery_time_question_does_not_become_address():
    state = extract_order_state([
        "Клиент: Доставка сегодня вечером",
        "Клиент: К 21:00 можно?",
    ])

    assert state.delivery_time == "21:00"
    assert state.address is None
