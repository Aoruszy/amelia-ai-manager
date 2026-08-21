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


def test_single_unmarked_contact_after_both_roles_prompt_defaults_to_sender():
    state = extract_order_state(
        [
            "Менеджер: Подскажите ваше имя и телефон, и имя с телефоном получателя.",
            "Клиент: Анна 89990000001",
        ]
    )

    assert state.sender_name == "Анна"
    assert state.sender_phone == "89990000001"
    assert state.recipient_name is None
    assert state.recipient_phone is None


def test_single_marked_recipient_contact_after_both_roles_prompt_stays_recipient():
    state = extract_order_state(
        [
            "Менеджер: Подскажите ваше имя и телефон, и имя с телефоном получателя.",
            "Клиент: получатель Мария 89990000002",
        ]
    )

    assert state.recipient_name == "Мария"
    assert state.recipient_phone == "89990000002"
    assert state.sender_name is None
    assert state.sender_phone is None
