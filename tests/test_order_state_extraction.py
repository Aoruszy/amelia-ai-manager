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
            "Клиент: Доставка, Гайдара 173, Даниил 89990000007, получатель Ольга 89990000008",
        ]
    )

    assert state.occasion == "девушке"
    assert state.budget == 7000
    assert state.colors == ["синий", "белый"]
    assert state.fulfillment_type == "delivery"
    assert state.delivery_date == "2026-08-09"
    assert state.delivery_time == "18:00"
    assert state.address == "Гайдара 173"
    assert state.sender_name == "Даниил"
    assert state.sender_phone == "89990000007"
    assert state.recipient_name == "Ольга"
    assert state.recipient_phone == "89990000008"
