from amelia_manager.order_state import extract_order_state


def test_delivery_accusative_form_dostavku_is_extracted():
    state = extract_order_state(["Клиент: Давайте доставку"])

    assert state.fulfillment_type == "delivery"
