from amelia_manager.order_state import extract_order_state


def test_recipient_contact_after_recipient_prompt_is_not_reused_as_sender():
    state = extract_order_state(
        [
            "Клиент: Здравствуйте нужна доставка на Гайдара 173",
            "Менеджер: Подскажите, пожалуйста, имя и номер телефона получателя?",
            "Клиент: Ольга 89990000005",
        ]
    )

    assert state.recipient_name == "Ольга"
    assert state.recipient_phone == "89990000005"
    assert state.sender_name is None
    assert state.sender_phone is None
