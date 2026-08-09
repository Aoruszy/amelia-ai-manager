from amelia_manager.order_state import extract_order_state


def test_extracts_payment_method_from_client_message():
    state = extract_order_state(["Клиент: оплачу переводом на карту"])

    assert state.payment_method == "transfer"


def test_extracts_no_postcard():
    state = extract_order_state(["Клиент: открытку не нужно"])

    assert state.postcard_text == "not_needed"
