from amelia_manager.order_state import extract_order_state


def test_until_time_is_not_budget():
    state = extract_order_state(["Клиент: заберу до 18:00"])

    assert state.budget is None
    assert state.delivery_time == "18:00"


def test_calendar_year_is_not_budget():
    state = extract_order_state(["Клиент: букет на 8 марта 2026"])

    assert state.budget is None
    assert state.delivery_date == "2026-03-08"


def test_delivery_address_with_apartment_after_na_is_extracted():
    state = extract_order_state(["Клиент: доставка на Ленинский 45 кв 12"])

    assert state.address == "Ленинский 45 кв 12"


def test_budget_thousand_phrase_is_extracted():
    state = extract_order_state(["Клиент: букет тысяч на 5"])

    assert state.budget == 5000


def test_budget_with_dot_thousands_separator_is_extracted():
    state = extract_order_state(["Клиент: букет за 3.500"])

    assert state.budget == 3500
