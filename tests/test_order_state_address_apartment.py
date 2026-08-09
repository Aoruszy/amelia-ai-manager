from amelia_manager.order_state import extract_order_state


def test_bare_delivery_address_keeps_apartment_after_house_number():
    state = extract_order_state(
        [
            "Клиент: Доставка",
            "Менеджер: Уточните, пожалуйста, адрес доставки?",
            "Клиент: ул. Гайдара 173 кв 14",
        ]
    )

    assert state.address == "ул. Гайдара 173 кв 14"
