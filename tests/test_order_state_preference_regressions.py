from amelia_manager.order_state import extract_order_state


def test_contact_line_after_delivery_address_does_not_overwrite_address():
    state = extract_order_state([
        "Клиент: Доставка завтра 14:00",
        "Клиент: Сергеева 10",
        "Клиент: Я Павел 89990000001, получатель Наталья 89990000002",
    ])

    assert state.address == "Сергеева 10"
    assert state.sender_name == "Павел"


def test_style_words_count_as_bouquet_preferences():
    assert "нежный стиль" in extract_order_state(["Клиент: Пусть будет нежный"]).colors
    assert "яркий стиль" in extract_order_state(["Клиент: Яркая, без хризантем"]).colors
    assert "корзина" in extract_order_state(["Клиент: нужна корзина цветов"]).colors
