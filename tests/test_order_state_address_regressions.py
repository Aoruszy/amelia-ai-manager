from amelia_manager.order_state import extract_order_state


def test_delivery_address_does_not_capture_delivery_date_time_line():
    state = extract_order_state([
        "Клиент: Бюджет 10000",
        "Клиент: Премиальный белый с зеленью",
        "Клиент: Доставка завтра 11:00",
        "Клиент: ул. Озерная 7",
    ])

    assert state.delivery_date == "2026-08-10"
    assert state.delivery_time == "11:00"
    assert state.address == "ул. Озерная 7"


def test_bare_street_name_number_is_delivery_address_after_delivery_context():
    state = extract_order_state([
        "Клиент: Доставка сегодня 20:00",
        "Клиент: Гайдара 173",
    ])

    assert state.address == "Гайдара 173"
