from amelia_manager.order_state import extract_order_state


def test_latest_fulfillment_choice_wins_when_client_switches_pickup_to_delivery():
    state = extract_order_state(
        [
            "Клиент: Самовывоз",
            "Менеджер: Самовывоз возможен в часы работы 09:00–20:00",
            "Клиент: Нужна доставка на Гайдара 173",
        ]
    )

    assert state.fulfillment_type == "delivery"
    assert state.address == "Гайдара 173"
