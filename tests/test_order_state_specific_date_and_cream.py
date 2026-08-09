from amelia_manager.order_state import extract_order_state


def test_extracts_specific_august_date_and_cream_color():
    state = extract_order_state([
        "Клиент: Добрый вечер! Нужен букет на 12 августа самовывоз в 12:00",
        "Клиент: Букет до 10000 рублей, по цветам нежно белый, кремовый",
    ])

    assert state.delivery_date == "12 августа"
    assert state.delivery_time == "12:00"
    assert state.budget == 10000
    assert state.fulfillment_type == "pickup"
    assert state.colors == ["белый", "кремовый", "нежный стиль"]
